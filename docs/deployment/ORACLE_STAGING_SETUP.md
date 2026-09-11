# Oracle Staging Setup

This guide creates a separate Oracle Cloud staging backend for Fortress. It
does not move production. Render, Neon production, Vercel production, and the
existing scheduled GitHub Actions remain live and unchanged.

## Architecture

GitHub Actions builds an ARM64 Docker image, pushes it to GitHub Container
Registry, SSHes into the Oracle VM, starts `fortress-backend` with Docker
Compose, and verifies `GET /api/health`.

Traffic flows like this:

`https://staging-api.example.com -> Caddy -> fortress-backend:8000 -> staging Neon DB`

The staging frontend should use `NEXT_PUBLIC_API_URL=https://staging-api.example.com`.
Do not change the production Vercel environment in this story.

## One-Time Oracle VM Setup

1. Create an Oracle Cloud VM.

   Use an Ampere A1 ARM VM. Start with 1 OCPU and 4 GB RAM. If scans are slow
   or memory is tight, use 2 OCPU and 8 GB RAM.

2. Choose an Ubuntu ARM image.

   Ubuntu 22.04 or 24.04 ARM64 is suitable.

3. Add your SSH public key.

   Keep the private key out of the repo. It will later be stored as a GitHub
   Actions secret.

4. Assign a public IPv4 address.

5. Open Oracle Cloud security-list or network security-group ingress:

   - TCP 22 from your IP for SSH.
   - TCP 80 from `0.0.0.0/0` for Caddy certificate issuance and HTTP redirect.
   - TCP 443 from `0.0.0.0/0` for HTTPS.

   Do not expose port 8000 publicly. Caddy talks to the backend inside Docker.

6. SSH into the VM:

   ```bash
   ssh ubuntu@YOUR_ORACLE_PUBLIC_IP
   ```

7. Install Docker:

   ```bash
   sudo apt-get update
   sudo apt-get install -y ca-certificates curl
   sudo install -m 0755 -d /etc/apt/keyrings
   sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
   sudo chmod a+r /etc/apt/keyrings/docker.asc
   . /etc/os-release
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
   sudo apt-get update
   sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo usermod -aG docker "$USER"
   ```

   Log out and SSH back in so your shell can use Docker without `sudo`.

8. Create the app directory:

   ```bash
   sudo mkdir -p /opt/fortress-dashboard
   sudo chown "$USER:$USER" /opt/fortress-dashboard
   ```

9. Create a staging Neon database.

   Prefer a separate Neon project. A separate database or schema is acceptable
   only if it is fully isolated and has separate credentials. Staging must not
   have credentials that can write to production research, evidence, or
   paper-trading tables.

10. Create the staging env file on the VM:

   ```bash
   cd /opt/fortress-dashboard
   nano .env.oracle.staging
   ```

   Use `.env.oracle.staging.example` from this repo as the template. Set
   `FORTRESS_ENV=staging`, `FORTRESS_DB_BACKEND=neon`, and a staging-only
   `DATABASE_URL`.

11. Add a production DB marker.

   Set `FORTRESS_PRODUCTION_DB_MARKERS` to one or more comma-separated
   substrings from the production database URL, such as the production Neon
   host or production database name. If the staging `DATABASE_URL` contains
   any marker, the app refuses to start.

12. Configure DNS.

   Add an `A` record:

   ```text
   staging-api.example.com -> YOUR_ORACLE_PUBLIC_IP
   ```

   Caddy will request and renew HTTPS certificates automatically. Do not
   upload certificates manually.

13. If Ubuntu firewall is enabled, allow only SSH, HTTP, and HTTPS:

   ```bash
   sudo ufw allow OpenSSH
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   sudo ufw status
   ```

## GitHub Secrets

Add these repository secrets:

- `ORACLE_HOST`: Oracle public IP or DNS name.
- `ORACLE_USER`: SSH user, usually `ubuntu`.
- `ORACLE_SSH_PRIVATE_KEY`: private key for that VM.
- `ORACLE_KNOWN_HOSTS`: output from `ssh-keyscan staging-api.example.com` or
  `ssh-keyscan YOUR_ORACLE_PUBLIC_IP`, reviewed before saving.
- `ORACLE_STAGING_BACKEND_URL`: `https://staging-api.example.com`.
- `GHCR_USERNAME`: your GitHub username.
- `GHCR_READ_TOKEN`: a GitHub token with `read:packages` access so the Oracle
  VM can pull the backend image.

The workflow uses GitHub's built-in token to push `ghcr.io` images.

## Deploy

Run the manual GitHub workflow:

```text
Actions -> Deploy Oracle Staging -> Run workflow
```

The workflow builds:

```text
ghcr.io/shivam039/fortress-dashboard-v2/fortress-backend:<git-sha>
```

Then it uploads the compose/Caddy/deploy files to `/opt/fortress-dashboard`
and runs:

```bash
FORTRESS_IMAGE=ghcr.io/shivam039/fortress-dashboard-v2/fortress-backend:<git-sha> \
ORACLE_STAGING_BACKEND_URL=https://staging-api.example.com/api/health \
/opt/fortress-dashboard/deploy-oracle-staging.sh
```

## Health Verification

The deploy workflow verifies:

```bash
curl -fsS https://staging-api.example.com/api/health
```

You should see:

```json
{"status":"healthy","version":"2.0","enable_new_features":false}
```

Also check read-only endpoints:

```bash
curl -i https://staging-api.example.com/api/auth/me
curl -i https://staging-api.example.com/api/paper-trades
curl -i https://staging-api.example.com/api/scan/history
```

Authenticated endpoints may return `401` without a token. That is acceptable.
They must not return startup errors or generic `500` responses.

## Frontend Staging

For a Vercel preview or separate staging frontend, set only the staging
environment variable:

```text
NEXT_PUBLIC_API_URL=https://staging-api.example.com
```

Do not change the Vercel production backend URL during this story.

## Playwright Smoke

The existing Playwright config already supports `PLAYWRIGHT_BASE_URL`.

Run smoke against a staging frontend:

```bash
cd frontend
PLAYWRIGHT_BASE_URL=https://staging-frontend.example.com npm run test:e2e:smoke
```

Required smoke coverage:

- login
- dashboard
- stock screener
- scan history
- paper-trading read path
- navigation
- no fatal API errors

Keep mutating E1/E2/E3 tests disabled unless the staging database is isolated
and the test has been explicitly reviewed as staging-safe.

## Safe Nifty 50 Scan

Use only the isolated staging database.

1. Set this in `/opt/fortress-dashboard/.env.oracle.staging`:

   ```text
   FORTRESS_AUTO_SCAN_UNIVERSES=Nifty 50
   ```

2. Restart staging:

   ```bash
   cd /opt/fortress-dashboard
   docker compose -f docker-compose.oracle-staging.yml up -d
   ```

3. Trigger one manual scan against the staging API only.

4. Verify:

   - scan completes
   - heartbeat updates
   - no stale-job false positive
   - paper-trading read path still works
   - stage timing and RSS logs appear

Do not enable an automatic staging E3 cron in this story.

## Observability

Use these VM commands:

```bash
cd /opt/fortress-dashboard
docker compose -f docker-compose.oracle-staging.yml ps
docker stats
docker logs fortress-backend --tail=200
docker logs fortress-caddy --tail=100
df -h
free -m
```

## Rollback

Images are deployed by immutable Git SHA. To roll back:

```bash
cd /opt/fortress-dashboard
FORTRESS_IMAGE=ghcr.io/shivam039/fortress-dashboard-v2/fortress-backend:PREVIOUS_GOOD_SHA \
ORACLE_STAGING_BACKEND_URL=https://staging-api.example.com/api/health \
./deploy-oracle-staging.sh
```

Verify `/api/health` after rollback.

## ARM Notes

The Dockerfile builds for `linux/arm64`. Dependencies such as pandas, numpy,
matplotlib, scipy-adjacent packages, and pandas-ta-classic should use published
ARM64 wheels where available. The GitHub workflow builds an ARM64 image, but
runtime memory behavior still needs verification on the Oracle Ampere VM during
the Nifty 50 staging scan.
