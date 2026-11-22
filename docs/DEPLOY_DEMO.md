# Client demo on an Oracle Always Free server

The whole TradeLens app (web, API, worker, PostgreSQL, Redis, HTTPS proxy) runs on one free
Oracle Cloud ARM server with `deploy/docker-compose.demo.yml`. The client opens one HTTPS address.
Account sign-ups, card checks and installers are done by you; nothing here needs a password in chat.

Time: about 1-2 hours the first time.

## 1. Oracle Cloud account (you)

1. Sign up at <https://signup.cloud.oracle.com> (Always Free). Oracle asks for a card to verify
   identity; Always Free resources are not charged. Choose the home region **India West (Mumbai)**
   or **India South (Hyderabad)**: it cannot be changed later.
2. Wait for the "account ready" email.

## 2. Create the server (you)

In the Oracle console: **Compute → Instances → Create instance**.

| Setting | Value |
| --- | --- |
| Name | `tradelens-demo` |
| Image | Canonical **Ubuntu 24.04** |
| Shape | **Ampere → VM.Standard.A1.Flex**, **4 OCPU, 24 GB** memory (Always Free) |
| Networking | Create a new virtual cloud network and public subnet; **assign a public IPv4 address** |
| SSH keys | "Generate a key pair for me" and **download both keys**, or upload your own public key |
| Boot volume | 100 GB |

If Oracle says "out of capacity" for A1, try again later or pick another availability domain.

Write down the **public IP address** of the instance.

## 3. Open ports 80 and 443 (you)

1. Instance → **Subnet** → **Security list** → **Add ingress rules**: source `0.0.0.0/0`,
   TCP, destination ports **80** and **443**.
2. Ubuntu on Oracle also blocks them in its own firewall; after you log in (step 4) run:

```bash
sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 4. Log in and install Docker (you)

From your PC (PowerShell), with the private key you downloaded:

```bash
ssh -i C:\path\to\private.key ubuntu@<PUBLIC_IP>
```

On the server, install Docker Engine from Docker's official Ubuntu instructions
(<https://docs.docker.com/engine/install/ubuntu/>, "Install using the apt repository"), then:

```bash
sudo usermod -aG docker ubuntu
exit
```

Log in again and check: `docker compose version`.

## 5. Get the code onto the server

The code must be committed and pushed first (ask Claude to commit; the demo needs the current
branch). Then on the server, either:

- **GitHub deploy key (recommended):** `ssh-keygen -t ed25519 -f ~/.ssh/tradelens -N ""`, add
  `~/.ssh/tradelens.pub` to the GitHub repository → Settings → Deploy keys (read-only), then
  `git clone git@github.com:pragmasystemsteam-coder/tradelens.git` with that key; or
- **Copy from your PC:** `scp -i C:\path\to\private.key -r tradelens ubuntu@<PUBLIC_IP>:~/`
  (skip `.venv`, `node_modules` and `web/.next`).

## 6. Settings file on the server (you)

```bash
cd ~/tradelens
cp deploy/.env.example deploy/.env
nano deploy/.env
```

Fill every value as in your local `deploy/.env`, with these differences:

| Key | Demo value |
| --- | --- |
| `DEMO_HOST` | your domain (e.g. `demo.tradelens.com` pointing to the IP), or `<IP with dashes>.sslip.io`, e.g. `129-154-10-20.sslip.io` |
| `ACME_EMAIL` | an email for Let's Encrypt certificate notices |
| `APP_ENV` | `staging` |
| `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `REDIS_PASSWORD` | **new** random values (`openssl rand -hex 24`), and the same values inside `DATABASE_URL` and `REDIS_URL` |
| `SESSION_SECRET`, `CSRF_SECRET` | **new** values (`openssl rand -hex 32`) |
| `DEV_DEMO_PASSWORD` | a password for the demo users you will give the client |
| `MARKET_DATA_PROVIDER`, `TWELVEDATA_API_KEY` | `twelvedata` and your key (real EUR/USD and gold) |
| `RAZORPAY_*` | test keys only (`RAZORPAY_MODE=test`) |
| `EMAIL_TRANSPORT`, `SMTP_*` | Brevo SMTP so sign-up emails arrive (free plan) |

Never paste these values into chat; `deploy/.env` stays only on the server.

## 7. Start it

```bash
cd ~/tradelens
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.demo.yml --env-file deploy/.env up --build -d
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.demo.yml --env-file deploy/.env ps
```

The first build takes 10-20 minutes on the ARM server. Then open `https://<DEMO_HOST>`.
Demo users: `free@demo.test` and `pro@demo.test` with `DEV_DEMO_PASSWORD`.

## 8. Update after new work

```bash
cd ~/tradelens && git pull
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.demo.yml --env-file deploy/.env up --build -d
```

## Notes

- The demo runs `APP_ENV=staging`: test payments only, demo users allowed, search engines told
  not to index it.
- Real customers, live Razorpay keys and the client's domains use the production file
  (`deploy/docker-compose.yml`, Cloudflare in front) at handover.
- Data stays in Docker volumes across restarts; `... down -v` deletes it.
