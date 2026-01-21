#!/usr/bin/env python3
"""
Elite Solana Token Scanner - WebSocket Version with Advanced Filtering
Only alerts on high-potential winners
Real-time monitoring via WebSocket
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
        self.callback = callback
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        self.websocket = None
        
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
                    self.websocket = websocket
                    logger.info("✅ Connected to Pump.fun WebSocket!")
                    
                    # Subscribe to new token creations
                    subscribe_message = {
                        "method": "subscribeNewToken"
                    }
                    await websocket.send(json.dumps(subscribe_message))
                    logger.info("Subscribed to new token events")
                    
                    current_delay = self.reconnect_delay
                    
                    # Listen for messages
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            await self.handle_message(data)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse message: {e}")
                        except Exception as e:
                            logger.error(f"Error handling message: {e}")
                            
            except websockets.exceptions.WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
            
            logger.info(f"Reconnecting in {current_delay} seconds...")
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
            logger.error(f"Error in handle_message: {e}")
    
    def parse_token_data(self, data: Dict) -> Optional[EarlyToken]:
        """Parse token data from WebSocket message"""
        try:
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
                twitter=data.get('twitter'),
                telegram=data.get('telegram'),
                website=data.get('website'),
            )
        except Exception as e:
            logger.error(f"Error parsing token: {e}")
            return None


class EliteTokenScanner:
    """Elite scanner with strict filtering for winners only"""
    
    def __init__(self, telegram_token: str, chat_id: str):
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.bot = Bot(token=telegram_token)
        self.session: Optional[aiohttp.ClientSession] = None
        
        self.pumpfun_ws = PumpFunWebSocketMonitor(callback=self.on_new_token)
        self.seen_tokens: Set[str] = set()
        
        # MOMENTUM CRITERIA - Catch tokens that have proven some legitimacy
        self.criteria = {
            # LIQUIDITY - Looking for established launches
            'min_pumpfun_liquidity': 20,      # $20+ SOL = decent support
            'max_pumpfun_liquidity': 200,     # <$200 SOL = room to grow
            
            # TIMING - Sweet spot after initial launch
            'max_token_age_seconds': 600,     # First 10 minutes (safer zone)
            
            # SOCIAL PROOF - Must look legitimate
            'require_socials': False,         # Nice to have but not required
            
            # NAME QUALITY
            'max_symbol_length': 8,           # Slightly longer OK
            'min_symbol_length': 3,           # Not too short
            
            # THEME REQUIREMENT - Broader themes
            'require_theme_match': True,
            'winning_themes': {
                'dogs': ['dog', 'doge', 'shiba', 'wif', 'bonk', 'pup', 'inu', 'puppy'],
                'cats': ['cat', 'popcat', 'kitty', 'meow', 'neko'],
                'memes': ['pepe', 'wojak', 'chad', 'gigachad', 'smug', 'apu', 'bobo'],
                'ai': ['ai', 'agent', 'gpt', 'chatgpt', 'claude', 'bot'],
                'political': ['trump', 'maga', 'biden', 'america'],
                'food': ['pizza', 'taco', 'burger', 'fries'],
            },
            
            # BLACKLIST - Auto-reject
            'blacklist_keywords': [
                # Obvious scams
                'test', 'scam', 'rug', 'honeypot',
                # Hype words (usually fail)
                'moon', 'gem', 'safe', '100x', '1000x', 
                'lambo', 'rocket', 'millionaire', 'rich',
                # Random/low effort
                'random', 'asdf', 'qwerty', 'zzzz',
            ],
            
            # QUALITY FILTERS - Less strict
            'banned_patterns': [
                r'\d{4,}',          # No "DOGE42069"
                r'[x×]\d{2,}',      # No "100x", "1000x"
            ],
            
            # PRIORITY THRESHOLD - Lower for more alerts
            'min_priority_score': 150,        # Only alert if score >= 150/200
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
        
        logger.info("Elite Token Scanner started!")
        await self.send_message(
            "🎯 <b>MOMENTUM SCANNER v3.1</b> 🎯\n\n"
            "⚡ WebSocket: REAL-TIME alerts\n"
            "📈 Strategy: Catch proven momentum\n\n"
            "<b>Criteria:</b>\n"
            f"💰 Liquidity: {self.criteria['min_pumpfun_liquidity']}-{self.criteria['max_pumpfun_liquidity']} SOL\n"
            f"⏱️ Age: First {self.criteria['max_token_age_seconds']//60} minutes\n"
            f"🎪 Themes: Dogs, Cats, Memes, AI, Political, Food\n"
            f"⭐ Min Priority: {self.criteria['min_priority_score']}/200\n\n"
            "Sweet spot = Safer launches with room to grow 📊"
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
        """Callback for new tokens"""
        try:
            if token.address in self.seen_tokens:
                return
            
            # Filter check
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
            
            logger.info(f"🔥 WINNER: {token.symbol} (Priority: {priority}/200)")
            
            # Send alert
            message = self.format_alert(token, priority)
            await self.send_message(message, disable_preview=True)
            
            self.seen_tokens.add(token.address)
            
        except Exception as e:
            logger.error(f"Error in on_new_token: {e}")
    
    def meets_criteria(self, token: EarlyToken) -> tuple[bool, str]:
        """Elite filtering - only winners pass"""
        
        # 1. Age check (seconds)
        age_seconds = (datetime.now() - token.timestamp).total_seconds()
        if age_seconds > self.criteria['max_token_age_seconds']:
            return False, f"Too old ({age_seconds:.0f}s)"
        
        # 2. Liquidity range
        liq = token.initial_liquidity
        if liq < self.criteria['min_pumpfun_liquidity']:
            return False, f"Low liquidity ({liq:.1f} SOL)"
        if liq > self.criteria['max_pumpfun_liquidity']:
            return False, f"High liquidity ({liq:.1f} SOL)"
        
        # 3. Social requirement
        if self.criteria.get('require_socials'):
            if not token.twitter and not token.telegram:
                return False, "No socials"
        
        # 4. Symbol length
        sym_len = len(token.symbol)
        if sym_len > self.criteria.get('max_symbol_length', 10):
            return False, f"Symbol too long ({sym_len})"
        if sym_len < self.criteria.get('min_symbol_length', 2):
            return False, f"Symbol too short ({sym_len})"
        
        # 5. Blacklist check
        name_lower = token.name.lower()
        symbol_lower = token.symbol.lower()
        
        for keyword in self.criteria['blacklist_keywords']:
            if keyword in name_lower or keyword in symbol_lower:
                return False, f"Blacklisted: {keyword}"
        
        # 6. Banned patterns
        for pattern in self.criteria.get('banned_patterns', []):
            if re.search(pattern, name_lower) or re.search(pattern, symbol_lower):
                return False, f"Banned pattern"
        
        # 7. Theme requirement
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
        
        # 8. Quality name (no excessive numbers)
        digit_count = sum(c.isdigit() for c in token.symbol)
        if digit_count > 1:
            return False, "Too many numbers"
        
        return True, "✅ Elite check passed"
    
    def calculate_priority(self, token: EarlyToken) -> int:
        """Calculate priority score (0-200) - Momentum focused"""
        score = 0
        
        # 1. SWEET SPOT TIMING (max 50 points)
        # Reward the 2-10 minute window (proven but early)
        age_seconds = (datetime.now() - token.timestamp).total_seconds()
        if 120 <= age_seconds <= 300:    # 2-5 minutes (SWEET SPOT)
            score += 50
        elif 60 <= age_seconds <= 600:   # 1-10 minutes (good)
            score += 45
        elif age_seconds < 120:          # Too early (risky)
            score += 35
        else:
            score += 20
        
        # 2. LIQUIDITY SWEET SPOT (max 40 points)
        liq = token.initial_liquidity
        if 30 <= liq <= 100:         # Perfect range
            score += 40
        elif 20 <= liq <= 150:       # Good range
            score += 35
        elif liq >= 15:              # Acceptable
            score += 25
        else:
            score += 10
        
        # 3. SOCIAL PROOF (max 30 points - less important)
        if token.twitter:
            score += 15
        if token.telegram:
            score += 15
        
        # 4. SYMBOL QUALITY (max 20 points)
        sym_len = len(token.symbol)
        if 3 <= sym_len <= 5:       # Perfect (DOGE, PEPE, WIF)
            score += 20
        elif sym_len <= 7:
            score += 15
        else:
            score += 5
        
        # 5. THEME MATCH (max 35 points)
        name_lower = token.name.lower()
        symbol_lower = token.symbol.lower()
        
        themes = self.criteria.get('winning_themes', {})
        for theme_name, keywords in themes.items():
            for keyword in keywords:
                if keyword in name_lower or keyword in symbol_lower:
                    # All hot themes
                    if theme_name in ['dogs', 'memes', 'ai', 'political']:
                        score += 35
                    else:
                        score += 25
                    break
        
        # 6. CLEAN NAME BONUS (max 25 points)
        if token.symbol.isalpha():  # No numbers/special chars
            score += 25
        elif token.symbol.replace('$', '').isalnum():
            score += 15
        
        return min(score, 200)
    
    def format_alert(self, token: EarlyToken, priority: int) -> str:
        """Format elite alert"""
        age_seconds = (datetime.now() - token.timestamp).total_seconds()
        
        # Priority emoji
        if priority >= 180:
            emoji = "🚨💎🚨"
            label = "PREMIUM GEM"
        elif priority >= 170:
            emoji = "🔥🔥🔥"
            label = "HOT LAUNCH"
        else:
            emoji = "🔥🔥"
            label = "QUALITY LAUNCH"
        
        msg = (
            f"{emoji} <b>{label}</b> {emoji}\n\n"
            f"<b>{token.symbol}</b> - {token.name}\n"
            f"📍 <code>{token.address}</code>\n\n"
            f"⏱️ Age: {age_seconds:.0f} seconds\n"
            f"💧 Liquidity: {token.initial_liquidity:.1f} SOL\n"
            f"⭐ Priority: {priority}/200\n"
        )
        
        if token.bonding_curve:
            msg += f"📈 Curve: <code>{token.bonding_curve[:10]}...</code>\n"
        
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
            f"\n📊 <b>TRADE NOW:</b>\n"
            f"<a href='https://www.axiomtrade.app/swap?inputMint=So11111111111111111111111111111111111111112&outputMint={token.address}'>Axiom</a> | "
            f"<a href='https://pump.fun/{token.address}'>Pump.fun</a> | "
            f"<a href='https://birdeye.so/token/{token.address}?chain=solana'>Birdeye</a>\n\n"
            f"⚡ <i>Elite Scanner - {age_seconds:.0f}s old</i>"
        )
        
        return msg
    
    async def run(self):
        """Main run loop"""
        websocket_task = asyncio.create_task(self.pumpfun_ws.connect_and_subscribe())
        
        # Cleanup old seen tokens every 10 minutes
        async def cleanup_task():
            while True:
                await asyncio.sleep(600)
                if len(self.seen_tokens) > 500:
                    logger.info("Cleaning seen tokens cache...")
                    self.seen_tokens.clear()
        
        cleanup = asyncio.create_task(cleanup_task())
        await asyncio.gather(websocket_task, cleanup)


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
    
    scanner = EliteTokenScanner(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    
    try:
        await scanner.start()
        await scanner.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await scanner.stop()


if __name__ == "__main__":
    asyncio.run(main())
