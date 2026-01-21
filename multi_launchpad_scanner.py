#!/usr/bin/env python3
"""
Multi-Launchpad Solana Token Scanner
Monitors: Pump.fun, USD1, BONK, Bags, Raydium, Jupiter, and more
Real-time alerts via WebSocket + API polling
"""

import asyncio
import aiohttp
import logging
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import os
import websockets

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
    source: str  # pumpfun, usd1, bonk, bags, raydium, jupiter
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
    pool_id: Optional[str] = None
    creator_reputation: Optional[str] = None  # 'elite', 'good', 'unknown', 'bad'


class PumpFunWebSocketMonitor:
    """Real-time WebSocket monitor for Pump.fun launches"""
    
    def __init__(self, callback):
        self.ws_url = "wss://pumpportal.fun/api/data"
        self.callback = callback
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        
    async def connect_and_subscribe(self):
        """Connect to WebSocket and subscribe to new token events"""
        current_delay = self.reconnect_delay
        
        while True:
            try:
                logger.info(f"Connecting to Pump.fun WebSocket...")
                
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10
                ) as websocket:
                    logger.info("✅ Pump.fun WebSocket connected!")
                    
                    subscribe_message = {"method": "subscribeNewToken"}
                    await websocket.send(json.dumps(subscribe_message))
                    
                    current_delay = self.reconnect_delay
                    
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            await self.handle_message(data)
                        except Exception as e:
                            logger.error(f"Error handling Pump.fun message: {e}")
                            
            except Exception as e:
                logger.error(f"Pump.fun WebSocket error: {e}")
            
            await asyncio.sleep(current_delay)
            current_delay = min(current_delay * 2, self.max_reconnect_delay)
    
    async def handle_message(self, data: Dict):
        """Process incoming WebSocket message"""
        try:
            if isinstance(data, dict):
                if data.get('txType') == 'create' or 'mint' in data:
                    token = self.parse_token_data(data)
                    if token:
                        await self.callback(token)
        except Exception as e:
            logger.error(f"Error in Pump.fun handle_message: {e}")
    
    def parse_token_data(self, data: Dict) -> Optional[EarlyToken]:
        """Parse token data from WebSocket message"""
        try:
            return EarlyToken(
                address=data.get('mint', ''),
                name=data.get('name', 'Unknown'),
                symbol=data.get('symbol', 'UNKNOWN'),
                source='pumpfun',
                initial_liquidity=float(data.get('initialBuy', 0) or data.get('vSolInBondingCurve', 0)),
                creator=data.get('traderPublicKey', ''),
                timestamp=datetime.fromtimestamp(data.get('timestamp', 0) / 1000) if data.get('timestamp') else datetime.now(),
                bonding_curve=data.get('bondingCurveKey'),
                market_cap=float(data.get('marketCapSol', 0)),
                twitter=data.get('twitter'),
                telegram=data.get('telegram'),
                website=data.get('website'),
            )
        except Exception as e:
            logger.error(f"Error parsing Pump.fun token: {e}")
            return None


class DexScreenerMonitor:
    """Monitor DexScreener for new Solana pairs (catches all DEXs)"""
    
    def __init__(self, callback, session):
        self.callback = callback
        self.session = session
        self.seen_pairs = set()
        self.api_url = "https://api.dexscreener.com/latest/dex/tokens"
        
    async def scan_new_pairs(self):
        """Scan for new pairs across all DEXs"""
        try:
            # Get recently created pairs on Solana
            url = "https://api.dexscreener.com/latest/dex/search/?q=solana"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    pairs = data.get('pairs', [])
                    
                    for pair in pairs[:50]:  # Top 50 recent
                        pair_id = pair.get('pairAddress')
                        if pair_id and pair_id not in self.seen_pairs:
                            token = self.parse_pair_data(pair)
                            if token:
                                self.seen_pairs.add(pair_id)
                                await self.callback(token)
                                
        except Exception as e:
            logger.error(f"DexScreener scan error: {e}")
    
    def parse_pair_data(self, pair: Dict) -> Optional[EarlyToken]:
        """Parse pair data to token"""
        try:
            base_token = pair.get('baseToken', {})
            
            # Determine source from DEX name
            dex_id = pair.get('dexId', '').lower()
            if 'raydium' in dex_id:
                source = 'raydium'
            elif 'orca' in dex_id:
                source = 'orca'
            elif 'jupiter' in dex_id:
                source = 'jupiter'
            else:
                source = f'dex_{dex_id}'
            
            return EarlyToken(
                address=base_token.get('address', ''),
                name=base_token.get('name', 'Unknown'),
                symbol=base_token.get('symbol', 'UNKNOWN'),
                source=source,
                initial_liquidity=float(pair.get('liquidity', {}).get('usd', 0)),
                creator='',
                timestamp=datetime.fromtimestamp(pair.get('pairCreatedAt', 0) / 1000) if pair.get('pairCreatedAt') else datetime.now(),
                market_cap=float(pair.get('fdv', 0) or 0),
                volume=float(pair.get('volume', {}).get('h24', 0) or 0),
                pool_id=pair.get('pairAddress'),
            )
        except Exception as e:
            logger.error(f"Error parsing DexScreener pair: {e}")
            return None


class BirdeyeMonitor:
    """Monitor Birdeye for new tokens (fast, often before DexScreener)"""
    
    def __init__(self, callback, session, api_key: Optional[str] = None):
        self.callback = callback
        self.session = session
        self.api_key = api_key
        self.base_url = "https://public-api.birdeye.so"
        self.seen_tokens = set()
        
    async def scan_new_tokens(self):
        """Scan for newly created tokens"""
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
                    items = data.get('data', {}).get('items', [])
                    
                    for item in items:
                        token_address = item.get('address')
                        if token_address and token_address not in self.seen_tokens:
                            token = self.parse_token_data(item)
                            if token:
                                self.seen_tokens.add(token_address)
                                await self.callback(token)
                                
        except Exception as e:
            logger.error(f"Birdeye scan error: {e}")
    
    def parse_token_data(self, data: Dict) -> Optional[EarlyToken]:
        """Parse Birdeye token data"""
        try:
            return EarlyToken(
                address=data.get('address', ''),
                name=data.get('name', 'Unknown'),
                symbol=data.get('symbol', 'UNKNOWN'),
                source='birdeye',
                initial_liquidity=float(data.get('liquidity', 0)),
                creator=data.get('creator', ''),
                timestamp=datetime.fromtimestamp(data.get('creationTime', 0)) if data.get('creationTime') else datetime.now(),
                market_cap=float(data.get('mc', 0)),
            )
        except Exception as e:
            logger.error(f"Error parsing Birdeye token: {e}")
            return None


class DeveloperReputationTracker:
    """Track and score token creators/developers"""
    
    def __init__(self):
        # Elite developers (known winners)
        self.elite_devs = set([
            # Add known good developer wallets here
            # Example format: 'wallet_address'
        ])
        
        # Bad actors (known ruggers)
        self.blacklisted_devs = set([
            # Add known scammer wallets here
        ])
        
        # Track developer history
        self.dev_history = {}  # {wallet: {'launches': [], 'success_rate': 0}}
        
    def check_developer(self, creator_wallet: str) -> str:
        """Check developer reputation"""
        if creator_wallet in self.elite_devs:
            return 'elite'
        
        if creator_wallet in self.blacklisted_devs:
            return 'bad'
        
        # Check history
        if creator_wallet in self.dev_history:
            history = self.dev_history[creator_wallet]
            success_rate = history.get('success_rate', 0)
            
            if success_rate > 0.5:
                return 'good'
            elif success_rate < 0.2:
                return 'bad'
        
        return 'unknown'
    
    def add_known_good_dev(self, wallet: str):
        """Add a known good developer"""
        self.elite_devs.add(wallet)
        logger.info(f"Added elite dev: {wallet[:8]}...")
    
    def add_known_bad_dev(self, wallet: str):
        """Blacklist a developer"""
        self.blacklisted_devs.add(wallet)
        logger.info(f"Blacklisted dev: {wallet[:8]}...")
    
    def update_dev_history(self, creator_wallet: str, success: bool):
        """Update developer's track record"""
        if creator_wallet not in self.dev_history:
            self.dev_history[creator_wallet] = {
                'launches': [],
                'successes': 0,
                'total': 0
            }
        
        history = self.dev_history[creator_wallet]
        history['total'] += 1
        if success:
            history['successes'] += 1
        
        history['success_rate'] = history['successes'] / history['total']


class MultiLaunchpadScanner:
    """Scanner for multiple Solana launchpads and DEXs"""
    
    def __init__(self, telegram_token: str, chat_id: str):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.bot = Bot(token=telegram_token)
        self.session: Optional[aiohttp.ClientSession] = None
        
        self.seen_tokens: Set[str] = set()
        
        # Initialize developer tracker
        self.dev_tracker = DeveloperReputationTracker()
        
        # Initialize monitors (will be set in start())
        self.pumpfun_ws = None
        self.dexscreener = None
        self.birdeye = None
        
        # MOMENTUM CRITERIA
        self.criteria = {
            # LIQUIDITY
            'min_liquidity': 20,              # $20+ liquidity
            'max_liquidity': 200,             # <$200 liquidity
            
            # TIMING
            'max_token_age_seconds': 600,     # First 10 minutes
            
            # SOURCE PREFERENCES (optional - filter by source)
            'allowed_sources': [
                'pumpfun',
                'raydium', 
                'orca',
                'jupiter',
                'birdeye',
                # Add more as needed
            ],
            
            # SOCIAL PROOF
            'require_socials': False,
            
            # NAME QUALITY
            'max_symbol_length': 8,
            'min_symbol_length': 3,
            
            # THEMES
            'require_theme_match': True,
            'winning_themes': {
                'dogs': ['dog', 'doge', 'shiba', 'wif', 'bonk', 'pup', 'inu', 'puppy'],
                'cats': ['cat', 'popcat', 'kitty', 'meow', 'neko'],
                'memes': ['pepe', 'wojak', 'chad', 'gigachad', 'smug', 'apu', 'bobo'],
                'ai': ['ai', 'agent', 'gpt', 'chatgpt', 'claude', 'bot'],
                'political': ['trump', 'maga', 'biden', 'america'],
                'food': ['pizza', 'taco', 'burger', 'fries'],
            },
            
            # BLACKLIST
            'blacklist_keywords': [
                'test', 'scam', 'rug', 'honeypot',
                'moon', 'gem', 'safe', '100x', '1000x',
                'lambo', 'rocket', 'millionaire', 'rich',
                'random', 'asdf', 'qwerty',
            ],
            
            'banned_patterns': [
                r'\d{4,}',
                r'[x×]\d{2,}',
            ],
            
            # PRIORITY
            'min_priority_score': 150,
            
            # DEVELOPER FILTERS
            'block_bad_devs': True,           # Auto-reject known ruggers
            'boost_good_devs': True,          # Boost priority for known good devs
            'elite_dev_bonus': 50,            # Priority bonus for elite devs
            'good_dev_bonus': 25,             # Priority bonus for good devs
        }
    
    async def start(self):
        """Initialize scanner"""
        import ssl
        try:
            self.session = aiohttp.ClientSession()
        except Exception as e:
            logger.warning(f"Using SSL bypass: {e}")
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context)
            )
        
        # Initialize monitors
        self.pumpfun_ws = PumpFunWebSocketMonitor(callback=self.on_new_token)
        self.dexscreener = DexScreenerMonitor(callback=self.on_new_token, session=self.session)
        self.birdeye = BirdeyeMonitor(callback=self.on_new_token, session=self.session)
        
        logger.info("Multi-Launchpad Scanner started!")
        await self.send_message(
            "🚀 <b>MULTI-LAUNCHPAD SCANNER v4.0</b> 🚀\n\n"
            "📡 Monitoring:\n"
            "• 🎪 Pump.fun (WebSocket)\n"
            "• 🌊 Raydium (DexScreener)\n"
            "• 🦅 Orca (DexScreener)\n"
            "• 🪐 Jupiter (DexScreener)\n"
            "• 📊 Birdeye API\n\n"
            "<b>Criteria:</b>\n"
            f"💰 Liquidity: ${self.criteria['min_liquidity']}-${self.criteria['max_liquidity']}\n"
            f"⏱️ Age: First {self.criteria['max_token_age_seconds']//60} minutes\n"
            f"🎪 Themes: Multiple winning narratives\n"
            f"⭐ Min Priority: {self.criteria['min_priority_score']}/200\n\n"
            "Catching launches across ALL platforms! 🎯"
        )
    
    async def stop(self):
        """Clean up"""
        if self.session:
            await self.session.close()
    
    async def send_message(self, message: str, disable_preview: bool = False):
        """Send to Telegram"""
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
        """Callback for new tokens from any source"""
        try:
            if token.address in self.seen_tokens:
                return
            
            # Check developer reputation
            if token.creator:
                token.creator_reputation = self.dev_tracker.check_developer(token.creator)
                
                # Block bad developers
                if self.criteria.get('block_bad_devs') and token.creator_reputation == 'bad':
                    logger.warning(f"🚫 {token.symbol}: Known bad developer {token.creator[:8]}...")
                    return
            
            # Source filter
            allowed = self.criteria.get('allowed_sources', [])
            if allowed and token.source not in allowed:
                logger.debug(f"❌ {token.symbol}: Source {token.source} not allowed")
                return
            
            # Criteria check
            passes, reason = self.meets_criteria(token)
            if not passes:
                logger.debug(f"❌ {token.symbol}: {reason}")
                return
            
            # Priority check
            priority = self.calculate_priority(token)
            min_priority = self.criteria.get('min_priority_score', 0)
            
            if priority < min_priority:
                logger.info(f"⚠️ {token.symbol}: Low priority ({priority}/{min_priority})")
                return
            
            # Log with dev reputation
            dev_indicator = ""
            if token.creator_reputation == 'elite':
                dev_indicator = " [ELITE DEV 👑]"
            elif token.creator_reputation == 'good':
                dev_indicator = " [GOOD DEV ✅]"
                
            logger.info(f"🔥 {token.source.upper()}: {token.symbol}{dev_indicator} (Priority: {priority}/200)")
            
            # Send alert
            message = self.format_alert(token, priority)
            await self.send_message(message, disable_preview=True)
            
            self.seen_tokens.add(token.address)
            
        except Exception as e:
            logger.error(f"Error in on_new_token: {e}")
    
    def meets_criteria(self, token: EarlyToken) -> tuple[bool, str]:
        """Check if token meets criteria"""
        
        # Age check
        age_seconds = (datetime.now() - token.timestamp).total_seconds()
        if age_seconds > self.criteria['max_token_age_seconds']:
            return False, f"Too old ({age_seconds:.0f}s)"
        
        # Liquidity (convert from USD if needed, assume 1 SOL = ~$100 for rough estimate)
        liq = token.initial_liquidity
        # If source is pump.fun, liquidity is in SOL, convert to USD estimate
        if token.source == 'pumpfun':
            liq = liq * 100  # Rough SOL to USD conversion
            
        if liq < self.criteria['min_liquidity']:
            return False, f"Low liquidity (${liq:.0f})"
        if liq > self.criteria['max_liquidity'] * 1000:  # Max in thousands
            return False, f"High liquidity (${liq:.0f})"
        
        # Symbol length
        sym_len = len(token.symbol)
        if sym_len > self.criteria.get('max_symbol_length', 10):
            return False, f"Symbol too long ({sym_len})"
        if sym_len < self.criteria.get('min_symbol_length', 2):
            return False, f"Symbol too short ({sym_len})"
        
        # Blacklist
        name_lower = token.name.lower()
        symbol_lower = token.symbol.lower()
        
        for keyword in self.criteria['blacklist_keywords']:
            if keyword in name_lower or keyword in symbol_lower:
                return False, f"Blacklisted: {keyword}"
        
        # Banned patterns
        for pattern in self.criteria.get('banned_patterns', []):
            if re.search(pattern, name_lower) or re.search(pattern, symbol_lower):
                return False, f"Banned pattern"
        
        # Theme requirement
        if self.criteria.get('require_theme_match'):
            has_theme = False
            themes = self.criteria.get('winning_themes', {})
            
            for theme_name, keywords in themes.items():
                for keyword in keywords:
                    if keyword in name_lower or keyword in symbol_lower:
                        has_theme = True
                        break
                if has_theme:
                    break
            
            if not has_theme:
                return False, "No theme match"
        
        # Quality name
        digit_count = sum(c.isdigit() for c in token.symbol)
        if digit_count > 1:
            return False, "Too many numbers"
        
        return True, "✅ Passed"
    
    def calculate_priority(self, token: EarlyToken) -> int:
        """Calculate priority score"""
        score = 0
        
        # Timing (2-5 min sweet spot)
        age_seconds = (datetime.now() - token.timestamp).total_seconds()
        if 120 <= age_seconds <= 300:
            score += 50
        elif 60 <= age_seconds <= 600:
            score += 45
        elif age_seconds < 120:
            score += 35
        else:
            score += 20
        
        # Liquidity
        liq = token.initial_liquidity
        if token.source == 'pumpfun':
            liq = liq * 100
            
        if 3000 <= liq <= 10000:
            score += 40
        elif 2000 <= liq <= 15000:
            score += 35
        elif liq >= 1500:
            score += 25
        
        # Socials
        if token.twitter:
            score += 15
        if token.telegram:
            score += 15
        
        # Symbol quality
        sym_len = len(token.symbol)
        if 3 <= sym_len <= 5:
            score += 20
        elif sym_len <= 7:
            score += 15
        
        # Theme match
        name_lower = token.name.lower()
        symbol_lower = token.symbol.lower()
        
        themes = self.criteria.get('winning_themes', {})
        for theme_name, keywords in themes.items():
            for keyword in keywords:
                if keyword in name_lower or keyword in symbol_lower:
                    if theme_name in ['dogs', 'memes', 'ai', 'political']:
                        score += 35
                    else:
                        score += 25
                    break
        
        # Clean name
        if token.symbol.isalpha():
            score += 25
        
        # DEVELOPER REPUTATION BONUS
        if token.creator_reputation == 'elite':
            score += self.criteria.get('elite_dev_bonus', 50)
        elif token.creator_reputation == 'good':
            score += self.criteria.get('good_dev_bonus', 25)
        
        return min(score, 250)  # Increased max to accommodate dev bonus
    
    def format_alert(self, token: EarlyToken, priority: int) -> str:
        """Format alert message"""
        age_seconds = (datetime.now() - token.timestamp).total_seconds()
        
        # Source emoji
        source_emoji = {
            'pumpfun': '🎪',
            'raydium': '🌊',
            'orca': '🐋',
            'jupiter': '🪐',
            'birdeye': '🦅',
        }.get(token.source, '📡')
        
        # Priority emoji
        if priority >= 180:
            emoji = "🚨💎🚨"
            label = "PREMIUM"
        elif priority >= 170:
            emoji = "🔥🔥🔥"
            label = "HOT"
        else:
            emoji = "🔥🔥"
            label = "QUALITY"
        
        liq_display = token.initial_liquidity
        liq_unit = "SOL" if token.source == 'pumpfun' else "USD"
        
        msg = (
            f"{emoji} <b>{label} LAUNCH</b> {emoji}\n\n"
            f"<b>{token.symbol}</b> - {token.name}\n"
            f"{source_emoji} Source: <b>{token.source.upper()}</b>\n"
            f"📍 <code>{token.address}</code>\n\n"
            f"⏱️ Age: {int(age_seconds//60)}m {int(age_seconds%60)}s\n"
            f"💧 Liquidity: {liq_display:.1f} {liq_unit}\n"
        )
        
        # Add market cap if available
        if token.market_cap > 0:
            if token.market_cap < 1000:
                mc_display = f"${token.market_cap:.0f}"
            elif token.market_cap < 1_000_000:
                mc_display = f"${token.market_cap/1000:.1f}K"
            else:
                mc_display = f"${token.market_cap/1_000_000:.2f}M"
            msg += f"💰 Market Cap: {mc_display}\n"
        
        msg += f"⭐ Priority: {priority}/250\n"
        
        # Developer reputation
        if token.creator_reputation:
            dev_emoji = {
                'elite': '👑',
                'good': '✅',
                'unknown': '❓',
                'bad': '⚠️'
            }.get(token.creator_reputation, '')
            
            dev_label = {
                'elite': 'ELITE DEVELOPER',
                'good': 'Good Dev',
                'unknown': 'Unknown Dev',
                'bad': 'Risky Dev'
            }.get(token.creator_reputation, '')
            
            if token.creator_reputation in ['elite', 'good']:
                msg += f"{dev_emoji} <b>{dev_label}</b>\n"
        
        # Socials
        socials = []
        if token.twitter:
            socials.append(f"<a href='{token.twitter}'>Twitter</a>")
        if token.telegram:
            socials.append(f"<a href='{token.telegram}'>Telegram</a>")
        if token.website:
            socials.append(f"<a href='{token.website}'>Web</a>")
        
        if socials:
            msg += f"\n🔗 {' | '.join(socials)}\n"
        
        # Trade links
        msg += (
            f"\n📊 <b>TRADE:</b>\n"
            f"<a href='https://www.axiomtrade.app/swap?inputMint=So11111111111111111111111111111111111111112&outputMint={token.address}'>Axiom</a> | "
        )
        
        if token.source == 'pumpfun':
            msg += f"<a href='https://pump.fun/{token.address}'>Pump.fun</a> | "
        
        msg += f"<a href='https://birdeye.so/token/{token.address}?chain=solana'>Birdeye</a>"
        
        if token.pool_id:
            msg += f" | <a href='https://dexscreener.com/solana/{token.pool_id}'>DexScreener</a>"
        
        msg += f"\n\n⚡ Multi-source scan - {int(age_seconds//60)}m old"
        
        return msg
    
    async def run(self):
        """Main run loop"""
        # Start Pump.fun WebSocket
        pumpfun_task = asyncio.create_task(self.pumpfun_ws.connect_and_subscribe())
        
        # Scan other sources every 30 seconds
        async def scan_other_sources():
            while True:
                try:
                    await self.dexscreener.scan_new_pairs()
                    await asyncio.sleep(2)
                    await self.birdeye.scan_new_tokens()
                except Exception as e:
                    logger.error(f"Error in scan loop: {e}")
                await asyncio.sleep(30)
        
        scan_task = asyncio.create_task(scan_other_sources())
        
        # Cleanup
        async def cleanup_task():
            while True:
                await asyncio.sleep(600)
                if len(self.seen_tokens) > 1000:
                    logger.info("Cleaning cache...")
                    self.seen_tokens.clear()
        
        cleanup = asyncio.create_task(cleanup_task())
        
        await asyncio.gather(pumpfun_task, scan_task, cleanup)


async def main():
    """Entry point"""
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID_HERE')
    
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("❌ Please set TELEGRAM_BOT_TOKEN")
        return
    
    if TELEGRAM_CHAT_ID == 'YOUR_CHAT_ID_HERE':
        print("❌ Please set TELEGRAM_CHAT_ID")
        return
    
    scanner = MultiLaunchpadScanner(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    
    try:
        await scanner.start()
        await scanner.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await scanner.stop()


if __name__ == "__main__":
    asyncio.run(main())
