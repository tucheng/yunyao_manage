# TLS deployment and trusted client identity

The project Nginx container is the public TLS boundary. Configure
`TLS_CERT_FILE` and `TLS_KEY_FILE` in `.env.prod` as absolute host paths to the
PEM certificate chain and private key. The files are mounted read-only and must
not be copied into an image or committed to Git.

Port 80 only returns a permanent redirect. All application traffic is served on
port 443. Do not publish the API, MySQL, Redis, or MinIO container ports.

Nginx deliberately overwrites `X-Forwarded-For` with the socket peer address.
Do not change it back to `$proxy_add_x_forwarded_for`: appending a client-supplied
forwarding chain would let callers bypass IP rate limits and administrator IP
restrictions.

Before starting production, validate the resolved Compose configuration:

```bash
docker compose --env-file .env.prod config
docker compose --env-file .env.prod up -d --build
```

After deployment, verify the redirect, HTTPS health endpoint, and certificate:

```bash
curl -I http://your-domain.example/health/live
curl -fsS https://your-domain.example/health/ready
openssl s_client -connect your-domain.example:443 -servername your-domain.example </dev/null
```

The first command must return `308` with an `https://` location. The second must
return a successful readiness response. The certificate chain and hostname
reported by the third command must be valid.
