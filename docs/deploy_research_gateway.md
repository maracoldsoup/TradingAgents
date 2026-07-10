# research_gateway 배포 (GCP e2-micro + Cloudflare Tunnel, $0/월)

이 문서는 `research_gateway`(FastAPI, `/api/breaking`·`/api/assets` 등)를
영구 무료 티어에 올리는 순서다. 계정 생성과 실제 배포 실행은 직접 해야
한다 — 여기 있는 건 그대로 복붙하면 되는 명령어 모음이다.

`docs/aimyticker_integration_architecture.md`의 마이그레이션 순서 2단계.

## 왜 이 조합인가

- GCP e2-micro Always Free: 월 $0 영구 (트라이얼 아님), us-west1/us-east1/
  us-central1 중 한 리전, 2vCPU 공유/1GB RAM/30GB 디스크. 이 서비스는
  `.pilot/` 밑에 수 MB짜리 JSON만 쓰고 5분 간격 폴링만 받으므로 충분하다.
- Cloudflare Tunnel: 무료·무제한, 포트 개방 없이 아웃바운드 연결만으로
  HTTPS 노출. GCP 방화벽 인바운드 규칙을 아예 안 열어도 된다.
- Oracle Cloud(Always Free, 스펙은 더 큼)도 대안이지만 최근(2026-06)
  무예고로 무료 한도를 절반으로 줄인 전례가 있고 리전 용량 부족으로
  프로비저닝이 실패하는 사례가 흔해 GCP를 우선한다.

## 0. 이미지 빌드 & 푸시

e2-micro(1GB RAM)에서 직접 `docker build`를 돌리면 메모리가 빠듯하다.
로컬이나 CI에서 빌드해서 레지스트리에 올리고, VM에서는 `pull`만 한다.

```bash
# 로컬에서 (Apple Silicon이면 --platform 필수: VM은 x86_64)
docker build --platform linux/amd64 -t ghcr.io/<GITHUB_USERNAME>/tradingagents:latest .
docker login ghcr.io -u <GITHUB_USERNAME>
docker push ghcr.io/<GITHUB_USERNAME>/tradingagents:latest
```

GitHub Container Registry(ghcr.io)는 public 리포면 무료다. 이미지를
공개하고 싶지 않으면 Docker Hub 무료 티어(private repo 1개)도 된다.

## 1. GCP 프로젝트 + VM 생성

```bash
# gcloud CLI 설치 후
gcloud auth login
gcloud projects create tradingagents-gateway --set-as-default
gcloud config set project tradingagents-gateway

# 결제 계정 연결은 콘솔에서 (카드 등록 필요, Always Free 한도 내엔 과금 없음)
# https://console.cloud.google.com/billing

gcloud services enable compute.googleapis.com

gcloud compute instances create research-gateway \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard
```

`us-central1`, `us-west1`, `us-east1`만 Always Free 대상이다. `pd-standard`
(HDD급)만 무료 — `pd-ssd`/`pd-balanced`는 과금된다.

## 2. VM에 Docker 설치 + 이미지 pull

```bash
gcloud compute ssh research-gateway --zone=us-central1-a

# VM 안에서:
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

docker pull ghcr.io/<GITHUB_USERNAME>/tradingagents:latest
```

## 3. 시크릿 파일 작성

```bash
# VM 안에서, ~/.env.research-gateway 생성 (git에 절대 커밋하지 않음)
cat > ~/.env.research-gateway <<'EOF'
RESEARCH_GATEWAY_API_KEY=<openssl rand -hex 32 로 생성한 값>
TOSS_SECURITIES_CLIENT_ID=<발급받은 값>
TOSS_SECURITIES_CLIENT_SECRET=<발급받은 값>
EOF
chmod 600 ~/.env.research-gateway
```

## 4. 컨테이너 실행 (systemd로 상시 기동)

```bash
sudo tee /etc/systemd/system/research-gateway.service <<'EOF'
[Unit]
Description=TradingAgents research_gateway
After=docker.service
Requires=docker.service

[Service]
Restart=always
ExecStartPre=-/usr/bin/docker rm -f research-gateway
ExecStart=/usr/bin/docker run --rm --name research-gateway \
  --env-file /home/%u/.env.research-gateway \
  -v research-gateway-pilot:/home/appuser/app/.pilot \
  -p 127.0.0.1:8653:8653 \
  ghcr.io/<GITHUB_USERNAME>/tradingagents:latest \
  serve --port 8653 \
  --rankings-snapshot-dir /home/appuser/app/.pilot/toss_rankings \
  --enable-background-jobs --rankings-poll-interval 300
ExecStop=/usr/bin/docker stop research-gateway

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now research-gateway
sudo systemctl status research-gateway
```

컨테이너는 `-p 127.0.0.1:8653:8653`로 로컬에만 열어둔다. 외부 노출은
Cloudflare Tunnel이 담당하므로 GCP 방화벽에 인바운드 포트를 열 필요가
없다.

`--enable-background-jobs`를 켜면 같은 프로세스 안에서 5분마다 Toss
랭킹을 수집한다(`tradingagents/scheduler.py`) — 별도 cron/systemd timer가
필요 없다. ETF/테마 프로필, candidate queue 갱신처럼 아직 스케줄러에
안 붙은 나머지 배치는 당분간 수동으로 돌리거나(`docker run ... build-queue`
등), 필요해지면 스케줄러에 job을 추가한다.

## 5. Cloudflare Tunnel

```bash
# VM 안에서
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared && sudo mv cloudflared /usr/local/bin/

cloudflared tunnel login          # 브라우저 인증, Cloudflare 계정 필요
cloudflared tunnel create research-gateway
cloudflared tunnel route dns research-gateway research.<본인도메인>

cat > ~/.cloudflared/config.yml <<'EOF'
tunnel: research-gateway
credentials-file: /home/<user>/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: research.<본인도메인>
    service: http://localhost:8653
  - service: http_status:404
EOF

sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

도메인이 없으면 `cloudflared tunnel --url http://localhost:8653`로 임시
`trycloudflare.com` 주소를 받아 먼저 테스트할 수 있다 (재시작할 때마다
주소가 바뀌므로 운영용은 아님).

## 6. 확인

```bash
curl https://research.<본인도메인>/healthz
curl -H "Authorization: Bearer <RESEARCH_GATEWAY_API_KEY>" https://research.<본인도메인>/api/breaking
```

## 7. aimyticker 쪽 마무리

- Supabase 프로젝트 시크릿에 추가: `RESEARCH_GATEWAY_URL=https://research.<본인도메인>`,
  `RESEARCH_GATEWAY_API_KEY=<위와 동일한 값>`.
- `db/migrations/033_sync_research_feed.sql` 맨 아래 주석 처리된
  `cron.schedule('sync-research-feed', ...)`를 Supabase SQL Editor에서
  `<PROJECT_REF>`/`<SERVICE_ROLE_KEY>`를 실제 값으로 바꿔 실행.

## 재배포

```bash
# 로컬에서 이미지 다시 빌드 + push 후, VM에서:
docker pull ghcr.io/<GITHUB_USERNAME>/tradingagents:latest
sudo systemctl restart research-gateway
```
