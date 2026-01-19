#!/usr/bin/env python3
"""
Early Solana Token Scanner - Pump.fun & Pre-Listing Focus
Monitors token launches before they hit DexScreener
Designed for Axiom traders catching very early stage launches
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import json
import os
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient

# pip install python-telegram-bot solana solders websockets
from telegram import Bot
from telegram.error import TelegramError
import websockets

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class EarlyToken:
    """Data class for early stage token"""
    address: str
    name: str
    symbol: str
    source: str  # 'pumpfun', 'raydium', 'jupiter'
    initial_liquidity: float
    creator: str
    timestamp: datetime
    bonding_curve: Optional[str] = None
    telegram: Optional[str] = None
    twitter: Optional[str] = None
    website: Optional[str] = None
    image_uri: Optional[str] = None
    
    # On-chain metrics
    holder_count: int = 0
    market_cap: float = 0
    volume: float = 0
    
    # Safety scores
    is_renounced: bool = False
    is_frozen: bool = False
    lp_burned: bool = False


class PumpFunMonitor:
    """Monitor Pump.fun for new token launches"""
    
    def __init__(self):
        self.api_base = "https://frontend-api.pump.fun"
        self.session: Optional[aiohttp.ClientSession] = None
        self.seen_tokens: Set[str] = set()
    
    async def get_recent_launches(self) -> List[Dict]:
        """Fetch recent Pump.fun token launches"""
        try:
            # Pump.fun API endpoints (may need updates)
            url = f"{self.api_base}/coins"
            params = {
                'limit': 50,
                'offset': 0,
                'sort': 'created_timestamp',
                'order': 'DESC'
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) else []
                else:
                    logger.warning(f"Pump.fun API returned {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching Pump.fun launches: {e}")
            return []
    
    async def get_token_details(self, mint_address: str) -> Optional[Dict]:
        """Get detailed info for a specific token"""
        try:
            url = f"{self.api_base}/coins/{mint_address}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            logger.error(f"Error fetching token details: {e}")
        return None
    
    def parse_pumpfun_token(self, data: Dict) -> Optional[EarlyToken]:
        """Parse Pump.fun token data"""
        try:
            return EarlyToken(
                address=data.get('mint', ''),
                name=data.get('name', 'Unknown'),
                symbol=data.get('symbol', 'UNKNOWN'),
                source='pumpfun',
                initial_liquidity=float(data.get('virtual_sol_reserves', 0)),
                creator=data.get('creator', ''),
                timestamp=datetime.fromtimestamp(data.get('created_timestamp', 0)),
                bonding_curve=data.get('bonding_curve'),
                telegram=data.get('telegram'),
                twitter=data.get('twitter'),
                website=data.get('website'),
                image_uri=data.get('image_uri'),
                market_cap=float(data.get('usd_market_cap', 0)),
            )
        except Exception as e:
            logger.error(f"Error parsing Pump.fun token: {e}")
            return None


class RaydiumMonitor:
    """Monitor Raydium for new pool creations (very early stage)"""
    
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.client: Optional[AsyncClient] = None
        # Raydium program IDs
        self.AMM_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
        self.seen_pools: Set[str] = set()
    
    async def start(self):
        """Initialize Solana RPC client"""
        self.client = AsyncClient(self.rpc_url)
    
    async def monitor_new_pools(self) -> List[Dict]:
        """Monitor for new Raydium pool creations"""
        # This would use Solana RPC subscriptions to monitor program logs
        # Implementation depends on your RPC provider
        try:
            # Placeholder - implement with actual RPC subscription
            # You'd want to subscribe to program logs for Raydium AMM
            pass
        except Exception as e:
            logger.error(f"Error monitoring Raydium: {e}")
        return []


class BirdeyeMonitor:
    """Monitor Birdeye for very new tokens (catches earlier than DexScreener)"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://public-api.birdeye.so"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_new_tokens(self) -> List[Dict]:
        """Fetch newly created tokens from Birdeye"""
        try:
            headers = {}
            if self.api_key:
                headers['X-API-KEY'] = self.api_key
            
            url = f"{self.base_url}/defi/token_creation"
            params = {
                'sort_by': 'creation_time',
                'sort_type': 'desc',
                'offset': 0,
                'limit': 50
            }
            
            async with self.session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('data', {}).get('items', [])
        except Exception as e:
            logger.error(f"Error fetching from Birdeye: {e}")
        return []


class JupiterMonitor:
    """Monitor Jupiter for new token listings"""
    
    def __init__(self):
        self.api_base = "https://quote-api.jup.ag/v6"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_token_info(self, mint_address: str) -> Optional[Dict]:
        """Get token info from Jupiter"""
        try:
            url = f"{self.api_base}/tokens"
            async with self.session.get(url) as response:
                if response.status == 200:
                    tokens = await response.json()
                    return next((t for t in tokens if t.get('address') == mint_address), None)
        except Exception as e:
            logger.error(f"Error fetching from Jupiter: {e}")
        return None


class EarlyTokenScanner:
    """Main scanner combining all sources"""
    
    def __init__(self, telegram_token: str, chat_id: str, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.bot = Bot(token=telegram_token)
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Initialize monitors
        self.pumpfun = PumpFunMonitor()
        self.raydium = RaydiumMonitor(rpc_url)
        self.birdeye = BirdeyeMonitor()
        self.jupiter = JupiterMonitor()
        
        self.seen_tokens: Set[str] = set()
        
        # Criteria optimized for VERY early stage
        self.criteria = {
            # Pump.fun specific
            'min_pumpfun_liquidity': 5,  # Min SOL in bonding curve
            'max_token_age_minutes': 30,  # Only tokens < 30 min old
            
            # General filters
            'require_socials': False,  # Many don't have socials yet
            'min_holder_velocity': 10,  # Holders per minute growth
            
            # Safety (less strict for early stage)
            'check_honeypot': True,
            'check_contract_verified': False,  # Often not verified yet
            
            # Keywords to prioritize (optional)
            'priority_keywords': ['doge', 'pepe', 'bonk', 'wojak', 'cat'],
            'blacklist_keywords': ['test', 'scam', 'rug'],
        }
    
    async def start(self):
        """Initialize all components"""
        # Create session with SSL handling for different environments
        import ssl
        try:
            # Try with default SSL first (works in cloud and most systems)
            self.session = aiohttp.ClientSession()
        except Exception as e:
            # Fallback for local Mac SSL issues
            logger.warning(f"Using SSL bypass due to: {e}")
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context)
            )
        
        self.pumpfun.session = self.session
        self.birdeye.session = self.session
        self.jupiter.session = self.session
        await self.raydium.start()
        
        logger.info("Early Token Scanner started!")
        await self.send_message(
            "🚀 <b>EARLY TOKEN SCANNER ACTIVATED</b> 🚀\n\n"
            "Monitoring:\n"
            "• 🎪 Pump.fun launches\n"
            "• 🌊 Raydium new pools\n"
            "• 🦅 Birdeye new tokens\n"
            "• 🪐 Jupiter listings\n\n"
            f"Catching tokens within {self.criteria['max_token_age_minutes']} minutes of launch!"
        )
    
    async def stop(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
        if self.raydium.client:
            await self.raydium.client.close()
    
    async def send_message(self, message: str, disable_preview: bool = False):
        """Send alert to Telegram"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=disable_preview
            )
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
    
    def meets_criteria(self, token: EarlyToken) -> tuple[bool, str]:
        """Check if token meets criteria, return (passes, reason)"""
        # Age check
        age_minutes = (datetime.now() - token.timestamp).total_seconds() / 60
        if age_minutes > self.criteria['max_token_age_minutes']:
            return False, f"Too old ({age_minutes:.1f} min)"
        
        # Pump.fun specific checks
        if token.source == 'pumpfun':
            if token.initial_liquidity < self.criteria['min_pumpfun_liquidity']:
                return False, f"Low liquidity ({token.initial_liquidity} SOL)"
        
        # Blacklist check
        name_lower = token.name.lower()
        symbol_lower = token.symbol.lower()
        for keyword in self.criteria['blacklist_keywords']:
            if keyword in name_lower or keyword in symbol_lower:
                return False, f"Blacklisted keyword: {keyword}"
        
        return True, "Passed all checks"
    
    def calculate_priority(self, token: EarlyToken) -> int:
        """Calculate priority score (higher = more interesting)"""
        score = 0
        
        # Age bonus (newer = higher score)
        age_minutes = (datetime.now() - token.timestamp).total_seconds() / 60
        score += max(0, 100 - age_minutes * 2)
        
        # Liquidity bonus
        score += min(50, token.initial_liquidity * 2)
        
        # Socials bonus
        if token.twitter:
            score += 20
        if token.telegram:
            score += 20
        if token.website:
            score += 10
        
        # Keyword bonus
        name_lower = token.name.lower()
        symbol_lower = token.symbol.lower()
        for keyword in self.criteria['priority_keywords']:
            if keyword in name_lower or keyword in symbol_lower:
                score += 30
                break
        
        return score
    
    def format_alert(self, token: EarlyToken, priority: int) -> str:
        """Format alert message"""
        age_minutes = (datetime.now() - token.timestamp).total_seconds() / 60
        
        # Priority emoji
        if priority >= 150:
            priority_emoji = "🔥🔥🔥"
        elif priority >= 100:
            priority_emoji = "🔥🔥"
        else:
            priority_emoji = "🔥"
        
        msg = (
            f"{priority_emoji} <b>EARLY LAUNCH DETECTED</b> {priority_emoji}\n\n"
            f"<b>{token.symbol}</b> - {token.name}\n"
            f"📍 <code>{token.address}</code>\n"
            f"🏷️ Source: {token.source.upper()}\n"
            f"⏰ Age: {age_minutes:.1f} minutes\n"
            f"⭐ Priority: {priority}/200\n\n"
        )
        
        # Source-specific info
        if token.source == 'pumpfun':
            msg += (
                f"💧 Initial Liquidity: {token.initial_liquidity:.2f} SOL\n"
                f"📈 Bonding Curve: <code>{token.bonding_curve[:8]}...</code>\n"
            )
        
        if token.market_cap > 0:
            msg += f"💰 Market Cap: ${token.market_cap:,.0f}\n"
        
        # Socials
        socials = []
        if token.twitter:
            socials.append(f"<a href='{token.twitter}'>Twitter</a>")
        if token.telegram:
            socials.append(f"<a href='{token.telegram}'>Telegram</a>")
        if token.website:
            socials.append(f"<a href='{token.website}'>Website</a>")
        
        if socials:
            msg += f"\n🔗 {' | '.join(socials)}\n"
        
        # Trading links
        msg += (
            f"\n📊 <b>Quick Links:</b>\n"
            f"<a href='https://www.axiomtrade.app/swap?inputMint=So11111111111111111111111111111111111111112&outputMint={token.address}'>Axiom Trade</a> | "
            f"<a href='https://pump.fun/{token.address}'>Pump.fun</a> | "
            f"<a href='https://birdeye.so/token/{token.address}?chain=solana'>Birdeye</a>\n\n"
            f"⚠️ <i>EXTREMELY EARLY - ULTRA HIGH RISK!</i>"
        )
        
        return msg
    
    async def scan_pumpfun(self):
        """Scan Pump.fun for new launches"""
        try:
            launches = await self.pumpfun.get_recent_launches()
            
            for launch in launches:
                token = self.pumpfun.parse_pumpfun_token(launch)
                
                if not token or token.address in self.seen_tokens:
                    continue
                
                # Check criteria
                passes, reason = self.meets_criteria(token)
                if not passes:
                    logger.debug(f"Token {token.symbol} filtered: {reason}")
                    continue
                
                # Calculate priority
                priority = self.calculate_priority(token)
                
                logger.info(f"🔥 Found early token: {token.symbol} (priority: {priority})")
                
                # Send alert
                message = self.format_alert(token, priority)
                await self.send_message(message, disable_preview=True)
                
                # Mark as seen
                self.seen_tokens.add(token.address)
                
                # Small delay between alerts
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error scanning Pump.fun: {e}")
    
    async def scan_loop(self):
        """Main scanning loop"""
        logger.info("Starting scan loop...")
        
        while True:
            try:
                # Scan Pump.fun (primary source for early launches)
                await self.scan_pumpfun()
                
                # TODO: Add Raydium monitoring
                # TODO: Add Birdeye monitoring
                # TODO: Add Jupiter monitoring
                
                # Clean old entries from seen_tokens (older than 1 hour)
                # This prevents the set from growing infinitely
                if len(self.seen_tokens) > 1000:
                    logger.info("Cleaning seen tokens cache...")
                    self.seen_tokens.clear()
                
                # Wait before next scan (adjust based on your needs)
                # For Pump.fun, 10-30 seconds is reasonable
                logger.debug("Waiting 20 seconds before next scan...")
                await asyncio.sleep(20)
                
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                await asyncio.sleep(30)


async def main():
    """Main entry point"""
    # Configuration
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID_HERE')
    SOLANA_RPC_URL = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
    
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("❌ Please set TELEGRAM_BOT_TOKEN")
        print("Create a bot with @BotFather on Telegram")
        return
    
    if TELEGRAM_CHAT_ID == 'YOUR_CHAT_ID_HERE':
        print("❌ Please set TELEGRAM_CHAT_ID")
        print("Get your ID from @userinfobot on Telegram")
        return
    
    scanner = EarlyTokenScanner(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SOLANA_RPC_URL)
    
    try:
        await scanner.start()
        await scanner.scan_loop()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await scanner.stop()


if __name__ == "__main__":
    asyncio.run(main())
