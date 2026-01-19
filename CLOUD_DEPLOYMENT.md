# 24/7 Cloud Deployment Guide

## Why Run in the Cloud?
- ✅ Runs 24/7 without your computer on
- ✅ Better uptime and reliability
- ✅ Faster internet connection
- ✅ No electricity cost on your end
- ✅ Auto-restarts if it crashes

---

## Option 1: Railway.app (EASIEST - RECOMMENDED)

### Step 1: Prepare Your Files
You'll need these files (already created for you):
- `early_token_scanner.py`
- `requirements.txt`
- `Procfile` (tells Railway how to run the bot)
- `runtime.txt` (specifies Python version)

### Step 2: Create Railway Account
1. Go to https://railway.app
2. Sign up with GitHub (recommended)
3. Verify your email

### Step 3: Deploy

**Method A - Direct Upload (Easiest):**
1. Click "New Project"
2. Select "Empty Project"
3. Click "Deploy from local files" or use Railway CLI
4. Upload all 4 files

**Method B - GitHub (Better for updates):**
1. Create a GitHub account if you don't have one
2. Create a new repository
3. Upload all 4 files to the repo
4. In Railway: "New Project" → "Deploy from GitHub repo"
5. Select your repo

### Step 4: Set Environment Variables
In Railway dashboard:
1. Click your project
2. Go to "Variables" tab
3. Add these variables:
   - `TELEGRAM_BOT_TOKEN` = your_bot_token
   - `TELEGRAM_CHAT_ID` = your_chat_id
   - `SOLANA_RPC_URL` = https://api.mainnet-beta.solana.com (optional)

### Step 5: Deploy!
Click "Deploy" - that's it! Your bot is now running 24/7.

**Costs:**
- Free: ~$5 credit/month (500 hours)
- Paid: $5/month for unlimited

---

## Option 2: Render.com

### Setup:
1. Go to https://render.com
2. Sign up with GitHub
3. Click "New +" → "Background Worker"
4. Connect your GitHub repo (or upload files)
5. Build command: `pip install -r requirements.txt`
6. Start command: `python3 early_token_scanner.py`
7. Add environment variables (same as Railway)
8. Click "Create Background Worker"

**Costs:**
- Free tier: Spins down after 15 min inactivity
- Always-on: $7/month

**Note:** Free tier will stop/start, causing gaps. Not ideal for catching launches.

---

## Option 3: DigitalOcean Droplet (Most Control)

### Step 1: Create Droplet
1. Go to https://digitalocean.com
2. Create account (get $200 credit with some promotions)
3. "Create" → "Droplets"
4. Choose:
   - Ubuntu 22.04
   - Basic plan ($4-6/month)
   - Cheapest option is fine

### Step 2: Connect via SSH
```bash
ssh root@your_droplet_ip
```

### Step 3: Setup Environment
```bash
# Update system
apt update && apt upgrade -y

# Install Python and pip
apt install python3 python3-pip -y

# Install screen (to keep bot running)
apt install screen -y

# Create directory
mkdir ~/crypto-bot
cd ~/crypto-bot
```

### Step 4: Upload Files
On your local Mac:
```bash
scp early_token_scanner.py root@your_droplet_ip:~/crypto-bot/
scp requirements.txt root@your_droplet_ip:~/crypto-bot/
```

Or use SFTP client like FileZilla.

### Step 5: Install Dependencies
```bash
cd ~/crypto-bot
pip3 install -r requirements.txt
```

### Step 6: Set Environment Variables
```bash
export TELEGRAM_BOT_TOKEN='your_token_here'
export TELEGRAM_CHAT_ID='your_chat_id_here'
```

### Step 7: Run in Screen
```bash
screen -S memecoin-bot
python3 early_token_scanner.py
```

Press `Ctrl + A`, then `D` to detach (bot keeps running)

To reconnect later: `screen -r memecoin-bot`

**Costs:** $4-6/month

---

## Option 4: PythonAnywhere

### Setup:
1. Go to https://pythonanywhere.com
2. Create account
3. Go to "Files" tab
4. Upload your files
5. Go to "Consoles" tab
6. Start a Bash console
7. Install dependencies: `pip3 install --user -r requirements.txt`
8. Run: `python3 early_token_scanner.py`

**Problem:** Free tier doesn't support always-on tasks. Need $5/month plan.

---

## Option 5: AWS EC2 Free Tier

### Setup (Similar to DigitalOcean):
1. Create AWS account
2. Launch EC2 instance (t2.micro is free for 12 months)
3. Connect via SSH
4. Follow same steps as DigitalOcean

**Costs:** Free for first year, then ~$8/month

---

## Option 6: Google Cloud (Free $300 Credit)

Same as AWS/DigitalOcean but with $300 free credit for 90 days.

---

## Option 7: Heroku Alternative - Fly.io

### Setup:
1. Go to https://fly.io
2. Install flyctl: `brew install flyctl` (on Mac)
3. Login: `flyctl auth login`
4. In your bot directory: `flyctl launch`
5. Set secrets: `flyctl secrets set TELEGRAM_BOT_TOKEN=xxx`
6. Deploy: `flyctl deploy`

**Costs:** Free tier available, then pay-as-you-go

---

## Comparison Table

| Platform | Ease | Cost | Best For |
|----------|------|------|----------|
| **Railway** | ⭐⭐⭐⭐⭐ | Free/$5 | Beginners |
| **Render** | ⭐⭐⭐⭐ | $7 | Simple deployment |
| **DigitalOcean** | ⭐⭐⭐ | $4-6 | Full control |
| **Fly.io** | ⭐⭐⭐⭐ | Free/paid | Modern apps |
| **AWS** | ⭐⭐ | Free/paid | Enterprise |
| **PythonAnywhere** | ⭐⭐⭐⭐ | $5 | Python focus |

---

## My Recommendation

### For You (Want Easy + Reliable):
**Start with Railway.app** - It's the easiest and has a generous free tier. If you outgrow it, upgrade for $5/month.

### If You Want Cheapest Long-Term:
**DigitalOcean** at $4/month is cheapest, but requires SSH knowledge.

### If You Want Free Forever:
**AWS/Google Cloud free tiers**, but more complex setup.

---

## Pro Tips

### 1. Monitor Your Bot
Add a health check message every hour:
```python
# Send hourly "still alive" message
if datetime.now().minute == 0:
    await self.send_message("✅ Bot still running...")
```

### 2. Set Up Alerts
Get notified if bot crashes:
- Use UptimeRobot (free) to ping a health endpoint
- Set up Railway/Render notifications

### 3. Logging
Log to a file so you can debug issues:
```python
logging.basicConfig(
    level=logging.INFO,
    filename='bot.log',
    format='%(asctime)s - %(levelname)s - %(message)s'
)
```

### 4. Auto-Restart
Most platforms auto-restart crashed apps. For VPS, use systemd or PM2.

---

## Quick Start: Railway in 5 Minutes

1. **Upload files to GitHub:**
   - Create repo on GitHub.com
   - Upload all 4 files (bot, requirements, Procfile, runtime.txt)

2. **Deploy to Railway:**
   - Go to railway.app
   - Sign in with GitHub
   - "New Project" → Select your repo
   - Add environment variables
   - Deploy!

3. **Check Telegram:**
   - You should get the startup message
   - Bot is now running 24/7!

---

## Troubleshooting

**"Build failed":**
- Check requirements.txt has all dependencies
- Check Procfile is correct
- Check logs in Railway dashboard

**"Bot not responding":**
- Check environment variables are set
- Check Telegram token is correct
- Check logs for errors

**"Out of memory":**
- Upgrade to paid plan ($5-7/month)
- Or optimize code to use less memory

---

## Need Help?

1. Check the platform's logs/dashboard
2. Most platforms have great documentation
3. Railway has a Discord server for support
4. I can help troubleshoot specific errors!

Let me know which option you want to try and I'll walk you through it!
