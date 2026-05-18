# Deploy

Single-VM, cloud-agnostic deployment. Works identically on AWS EC2, Azure VM, GCP Compute, DigitalOcean, Hetzner — anywhere you can SSH into Ubuntu 22.04+/24.04. Credentials live in `backend/.env` on the VM (chmod 600). On AWS specifically, you can blank the AWS keys in `.env` and attach an instance role instead — the SDK switches modes automatically. No code changes either way.

## What gets installed

| Component | Where | How it's run |
|---|---|---|
| Frontend (`frontend/dist/`) | served as static files by Nginx | n/a |
| Backend (Express, port 4000, loopback only) | `wedding-backend` PM2 app | PM2 → systemd on boot |
| Email worker (Solace consumer) | `wedding-email` PM2 app | PM2 → systemd on boot |
| Nginx | reverse proxy + static host on port 80 | systemd |

```
Internet ──:80──► Nginx ─┬─ /          → /opt/wedding/frontend/dist  (static)
                         └─ /api/*     → http://127.0.0.1:4000       (backend)
                                                       │
                                            (PM2)     │
                                              └──── wedding-email
                                                  (no inbound; outbound to Solace + SMTP)
```

## Prerequisites

- A VM with **Ubuntu 22.04 or 24.04**, public IP, SSH access, at least **1 GB RAM** (`t4g.small` / `B1ms` / `e2-small` all fit)
- Inbound firewall: `22` from your IP, `80` and `443` from anywhere
- Outbound: unrestricted is simplest (or at minimum: 443 to AWS APIs, 55555/55443 to your Solace broker, 587 to your SMTP host)
- The Solace queue `EMAIL_SOLACE_QUEUE` already provisioned with a topic subscription to `wedding/alerts/photos/email/>` — see [project README](../README.md#broker-setup)

## Cloud-specific provisioning

The differences across clouds are entirely in **how you launch the VM and open ports** — the bootstrap script itself is identical.

### AWS EC2
1. Launch `t4g.small` Ubuntu 24.04 (ARM Graviton) in your preferred region. ~$12/mo.
2. Security group: inbound 22 from your IP, 80 + 443 from `0.0.0.0/0`.
3. Allocate an Elastic IP and associate it.
4. **Optional, AWS-only — drop the long-lived AWS keys**: create an IAM role from [`docs/aws-iam-policy.json`](../docs/aws-iam-policy.json) (replace placeholders for bucket, region, account, collection), attach as instance profile, and leave `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` blank in `.env`.

### Azure VM
1. Create a `Standard_B1ms` Ubuntu 24.04 VM in your resource group. ~$15/mo.
2. NSG: inbound 22 from your IP, 80 + 443 from `Internet`.
3. Use the credentials-in-`.env` path — Azure has no equivalent to AWS instance roles for AWS service auth.

### GCP Compute Engine
1. Create an `e2-small` Ubuntu 24.04 instance. ~$13/mo.
2. Firewall rules: tag the VM `http-server` and `https-server` (auto-creates rules), add SSH manually.
3. Reserve a static external IP.
4. Use the credentials-in-`.env` path.

### Anything else (DigitalOcean / Hetzner / Linode / on-prem)
Spin up Ubuntu 22.04+/24.04, expose 22/80/443, point DNS at it. Same script.

## Deploy

```bash
# 1. SSH into the VM as a user with sudo, then:
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/<you>/wedding-photo-sharing.git /opt/wedding
cd /opt/wedding

# 2. Run the bootstrap (installs Node 20, PM2, Nginx, builds the app, starts everything)
sudo bash deploy/bootstrap.sh

# 3. Edit the env file with your real credentials
sudo -u wedding ${EDITOR:-vi} /opt/wedding/backend/.env

# 4. Restart so the apps pick up the new env
sudo -u wedding pm2 restart all

# 5. Browse to http://<vm-ip>/
```

The script is idempotent — re-run it any time after pulling new code; it will rebuild and reload PM2 without recreating users or env files.

## Updating after code changes

```bash
cd /opt/wedding
sudo -u wedding git pull
sudo -u wedding npm ci
sudo -u wedding npm run build
sudo -u wedding pm2 restart all
```

Or just re-run `sudo bash deploy/bootstrap.sh` — it does all of the above and is safe to run repeatedly.

## HTTPS with Let's Encrypt

Once you have a domain pointing at the VM:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.example.com
```

Certbot edits `/etc/nginx/sites-available/wedding` in place to add the cert + a 443 server block, and sets up a renewal cron. The included Nginx config is structured so certbot's edits drop in cleanly.

## Operations

```bash
sudo -u wedding pm2 status       # both processes should be 'online'
sudo -u wedding pm2 logs         # tail combined logs
sudo -u wedding pm2 logs wedding-email   # one process only
sudo -u wedding pm2 restart wedding-backend
sudo journalctl -u nginx -f      # nginx logs
```

Logs also land at `/var/log/wedding/{backend,email}.{out,err}.log` (configured in `ecosystem.config.cjs`).

## Rotating credentials

The `.env` file is the single source of truth. To rotate any credential:

```bash
sudo -u wedding ${EDITOR:-vi} /opt/wedding/backend/.env
sudo -u wedding pm2 restart all
```

Recommended cadence:
- AWS IAM user access key: every 90 days (`aws iam create-access-key` → update `.env` → `aws iam delete-access-key`)
- Gmail App Password: revoke + reissue if the VM is ever decommissioned
- Solace password: per your broker's rotation policy

## Cost (monthly, indicative)

| Item | Approx. |
|---|---|
| VM (`t4g.small` / `B1ms` / `e2-small`) | $12–$15 |
| 20–30 GB SSD | $2–$4 |
| Static / Elastic IP | $0–$4 |
| AWS S3 storage + Rekognition + data transfer | varies; $1–$10 for low-volume use |
| Solace broker | external (your existing setup) |
| **Total** | **~$15–$30/month** |
