# Deploying Boswell

Quick deployment guide for getting Boswell running on a server.

## Option 1: Railway (Fastest)

1. Push your code to GitHub
2. Go to [railway.app](https://railway.app) and create new project
3. Connect your GitHub repo
4. Add PostgreSQL from the marketplace
5. Set environment variables in the dashboard:
   - `CLAUDE_API_KEY`
   - `DEEPGRAM_API_KEY`
   - `ELEVENLABS_API_KEY`
   - `DAILY_API_KEY`
   - `SECRET_KEY` (generate: `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `ADMIN_EMAIL`
   - `ADMIN_PASSWORD`
6. Deploy!

For the voice worker, add a second service from the same repo and set:
- Start command: `./scripts/start_worker.sh`

Railway gives you: `your-app.up.railway.app`

## Option 2: Render

1. Push to GitHub
2. Go to [render.com](https://render.com) → New Blueprint
3. Connect your repo (it will detect `render.yaml`)
4. Fill in the environment variables when prompted
5. Deploy!

Render gives you: `your-app.onrender.com`

## Option 3: VPS (DigitalOcean, Linode, etc.)

SSH into your server and run:

```bash
# Clone repo
git clone https://github.com/youruser/boswell.git
cd boswell

# Create .env file
cp .env.example .env
nano .env  # Fill in your API keys

# Build and run
docker compose -f docker-compose.prod.yml up -d

# Check status
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f
```

### Add SSL with Caddy (recommended)

```bash
# Install Caddy
sudo apt install -y caddy

# Configure reverse proxy
sudo tee /etc/caddy/Caddyfile << 'CADDYEOF'
your-domain.com {
    reverse_proxy localhost:8000
}
CADDYEOF

# Reload Caddy
sudo systemctl reload caddy
```

## Required Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Auto on Railway/Render |
| `CLAUDE_API_KEY` | Anthropic API key | Yes |
| `DEEPGRAM_API_KEY` | Deepgram STT API key | Yes |
| `ELEVENLABS_API_KEY` | ElevenLabs TTS API key | Yes |
| `DAILY_API_KEY` | Daily.co video/audio API key | Yes |
| `SECRET_KEY` | Session signing key (32+ chars) | Yes |
| `ADMIN_EMAIL` | Admin login email | Yes |
| `ADMIN_PASSWORD` | Admin login password | Yes |
| `BASE_URL` | Public URL (for email links) | Production |
| `RESEND_API_KEY` | Email delivery (optional) | For invites |

## Health Check

The web service exposes `/health` for health checks.

## Troubleshooting

**Bot not joining rooms?**
- Check worker logs: `docker compose logs worker`
- Verify DAILY_API_KEY is correct
- Ensure worker container is running

**Database connection errors?**
- Check DATABASE_URL format: `postgresql+asyncpg://user:pass@host:5432/db`
- Ensure database is running and healthy

**Voice cutting out?**
- Check DEEPGRAM_API_KEY and ELEVENLABS_API_KEY
- Monitor worker logs for API errors
