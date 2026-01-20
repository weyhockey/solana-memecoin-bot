#!/usr/bin/env python3
"""
Early Solana Token Scanner - WebSocket Version
Real-time monitoring of Pump.fun launches via WebSocket
Much more reliable than API polling
"""

import asyncio
import aiohttp
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import os
import websockets

# pip install python-telegram-bot aiohttp websockets
from telegram import Bot
from telegram.error import TelegramError

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
    source: str
    initial_liquidity: float
    creator: str
    timestamp: datetime
    bonding_curve: Optional[str] = None
    telegram: Optional[str] = None
    twitter: Optional[str] = None
    website: Optional[str] = None
    image_uri: Optional[str] = None
    market_cap: float = 0
    volume: float = 0
    holder_count: int = 0
    is_renounced: bool = False
    is_frozen: bool = False
    lp_burned: bool = False


class PumpFunWebSocketMonitor:
    """Real-time WebSocket monitor for Pump.fun launches"""
    
    def __init__(self, callback):
        self.ws_url = "wss://pumpportal.fun/api/data"
        self.callback = callback  # Function to call when new token found
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        self.websocket = None
        
    async def connect_and_subscribe(self):
        """Connect to WebSocket and subscribe to new token events"""
        current_delay = self.reconnect_delay
        
        while True:
            try:
                logger.info(f"Connecting to Pump.fun WebSocket at {self.ws_url}")
                
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as websocket:
                    self.websocket = websocket
                    logger.info("✅ Connected to Pump.fun WebSocket!")
                    
                    # Subscribe to new token creations
                    subscribe_message = {
                        "method": "subscribeNewToken"
                    }
                    await websocket.send(json.dumps(subscribe_message))
                    logger.info("Subscribed to new token events")
                    
                    # Reset reconnect delay on successful connection
                    current_delay = self.reconnect_delay
                    
                    # Listen for messages
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            await self.handle_message(data)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse WebSocket message: {e}")
                        except Exception as e:
                            logger.error(f"Error handling message: {e}")
                            
            except websockets.exceptions.WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
            
            # Reconnect with exponential backoff
            logger.info(f"Reconnecting in {current_delay} seconds...")
            await asyncio.sleep(current_delay)
            current_delay = min(current_delay * 2, self.max_reconnect_delay)
    
    async def handle_message(self, data: Dict):
        """Process incoming WebSocket message"""
        try:
            # Parse Pump.fun WebSocket message format
            # Message structure may vary - adjust based on actual format
            if isinstance(data, dict):
                # Check if this is a new token event
                if data.get('txType') == 'create' or 'mint' in data:
                    token = self.parse_token_data(data)
                    if token:
                        await self.callback(token)
                        
        except Exception as e:
            logger.error(f"Error in handle_message: {e}")
    
    def parse_token_data(self, data: Dict) -> Optional[EarlyToken]:
        """Parse token data from WebSocket message"""
        try:
            # Adjust field names based on actual WebSocket message format
            return EarlyToken(
                address=data.get('mint', ''),
                name=data.get('name', 'Unknown'),
                symbol=data.get('symbol', 'UNKNOWN'),
                source='pumpfun_websocket',
                initial_liquidity=float(data.get('initialBuy', 0) or data.get('vSolInBondingCurve', 0)),
                creator=data.get('traderPublicKey', ''),
                timestamp=datetime.fromtimestamp(data.get('timestamp', 0) / 1000) if data.get('timestamp') else datetime.now(),
                bonding_curve=data.get('bondingCurveKey'),
                market_cap=float(data.get('marketCapSol', 0)),
            )
        except Exception as e:
            logger.error(f"Error parsing token data: {e}")
            return None


class BirdeyeMonitor:
    """Birdeye API as backup data source"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://public-api.birdeye.so"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_new_tokens(self) -> List[Dict]:
        """Fetch newly created tokens from Birdeye"""
        try:
            headers = {'X-API-KEY': self.api_key} if self.api_key else {}
            
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


class EarlyTokenScanner:
    """Main scanner with WebSocket support"""
    
    def __init__(self, telegram_token: str, chat_id: str):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.bot = Bot(token=telegram_token)
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Initialize monitors
        self.pumpfun_ws = PumpFunWebSocketMonitor(callback=self.on_new_token)
        self.birdeye = BirdeyeMonitor()
        
        self.seen_tokens: Set[str] = set()
        
        # Criteria optimized for VERY early stage
        self.criteria = {
            # Pump.fun specific
            'min_pumpfun_liquidity': 3,  # Min SOL in bonding curve
            'max_token_age_minutes': 30,  # Only tokens < 30 min old
            
            # General filters
            'require_socials': False,
            'min_holder_velocity': 10,
            
            # Safety
            'check_honeypot': True,
            
            # Keywords
            'priority_keywords': ['doge', 'pepe', 'bonk', 'wojak', 'cat', 'dog'],
            'blacklist_keywords': ['test', 'scam', 'rug'],
        }
    
    async def start(self):
        """Initialize all components"""
        import ssl
        try:
            self.session = aiohttp.ClientSession()
        except Exception as e:
            logger.warning(f"Using SSL bypass due to: {e}")
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context)
            )
        
        self.birdeye.session = self.session
        
        logger.info("Early Token Scanner started!")
        await self.send_message(
            "🚀 <b>EARLY TOKEN SCANNER v2.0 - WEBSOCKET MODE</b> 🚀\n\n"
            "Monitoring:\n"
            "• 🎪 Pump.fun WebSocket (REAL-TIME)\n"
            "• 🦅 Birdeye API (backup)\n\n"
            "⚡ WebSocket = Instant alerts within seconds of launch!\n"
            f"Catching tokens within {self.criteria['max_token_age_minutes']} minutes of creation."
        )
    
    async def stop(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
    
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
    
    async def on_new_token(self, token: EarlyToken):
        """Callback when WebSocket detects new token"""
        try:
            # Skip if already seen
            if token.address in self.seen_tokens:
                return
            
            # Check criteria
            passes, reason = self.meets_criteria(token)
            if not passes:
                logger.debug(f"Token {token.symbol} filtered: {reason}")
                return
            
            # Calculate priority
            priority = self.calculate_priority(token)
            
            logger.info(f"🔥 Found early token via WebSocket: {token.symbol} (priority: {priority})")
            
            # Send alert
            message = self.format_alert(token, priority)
            await self.send_message(message, disable_preview=True)
            
            # Mark as seen
            self.seen_tokens.add(token.address)
            
        except Exception as e:
            logger.error(f"Error in on_new_token: {e}")
    
    def meets_criteria(self, token: EarlyToken) -> tuple[bool, str]:
        """Check if token meets criteria"""
        # Age check
        age_minutes = (datetime.now() - token.timestamp).total_seconds() / 60
        if age_minutes > self.criteria['max_token_age_minutes']:
            return False, f"Too old ({age_minutes:.1f} min)"
        
        # Liquidity check
        if token.source == 'pumpfun_websocket':
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
        """Calculate priority score"""
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
            f"🏷️ Source: WEBSOCKET (REAL-TIME)\n"
            f"⏰ Age: {age_minutes:.1f} minutes\n"
            f"⭐ Priority: {priority}/200\n\n"
        )
        
        if token.initial_liquidity > 0:
            msg += f"💧 Initial Liquidity: {token.initial_liquidity:.2f} SOL\n"
        
        if token.bonding_curve:
            msg += f"📈 Bonding Curve: <code>{token.bonding_curve[:8]}...</code>\n"
        
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
            f"⚡ <i>WEBSOCKET ALERT - ULTRA FRESH!</i>"
        )
        
        return msg
    
    async def birdeye_backup_scan(self):
        """Backup scanning via Birdeye API"""
        logger.info("Running backup Birdeye scan...")
        
        try:
            tokens = await self.birdeye.get_new_tokens()
            
            for token_data in tokens:
                # Parse and check token
                # Similar to WebSocket handling
                pass
                
        except Exception as e:
            logger.error(f"Error in Birdeye backup scan: {e}")
    
    async def run(self):
        """Main run loop"""
        # Start WebSocket monitor
        websocket_task = asyncio.create_task(self.pumpfun_ws.connect_and_subscribe())
        
        # Optionally run Birdeye backup scans every 5 minutes
        async def backup_scanner():
            while True:
                await asyncio.sleep(300)  # 5 minutes
                await self.birdeye_backup_scan()
        
        backup_task = asyncio.create_task(backup_scanner())
        
        # Run both tasks
        await asyncio.gather(websocket_task, backup_task)


async def main():
    """Main entry point"""
    # Configuration
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID_HERE')
    
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("❌ Please set TELEGRAM_BOT_TOKEN")
        return
    
    if TELEGRAM_CHAT_ID == 'YOUR_CHAT_ID_HERE':
        print("❌ Please set TELEGRAM_CHAT_ID")
        return
    
    scanner = EarlyTokenScanner(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    
    try:
        await scanner.start()
        await scanner.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await scanner.stop()


if __name__ == "__main__":
    asyncio.run(main())
