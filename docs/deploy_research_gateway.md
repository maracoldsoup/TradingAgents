# research_gateway 배포

`research_gateway`(FastAPI, `/api/breaking`·`/api/assets` 등)를 띄우는
두 가지 경로. `docs/aimyticker_integration_architecture.md`의 마이그레이션
순서 2단계.

- **지금(파일럿 단계) 쓰는 방식**: 로컬 맥 + Cloudflare Tunnel, $0.
- **나중(실제 서비스) 쓸 방식**: GCP e2-micro + Cloudflare Tunnel, 월 약
  5,500원(~$3.65). 아래 "실제 서비스 단계" 섹션.

두 경로 다 실제로 해봤다. 계정 생성과 실행은 직접 해야 한다 — 여기 있는
건 그대로 복붙하면 되는 명령어 모음이다.

## 지금 쓰는 방식: 로컬 맥 + Cloudflare Tunnel ($0)

GCP를 먼저 시도했다가 두 가지 문제로 파일럿 단계에서는 이 방식으로
바꿨다: (1) GCP는 2024년부터 VM에 붙는 외부 IP가 임시든 고정이든 시간당
$0.005(월 ~5,500원) 과금이라 "완전 무료"가 아니었고, (2) Toss 증권 API가
IP 허용 목록을 요구해서 새로 만든 GCP VM의 IP가 막혔다(로컬 맥 IP는 이미
등록돼 있어서 문제없이 통과). Docker 이미지 빌드·레지스트리 계정도 필요
없다 — 로컬 가상환경에서 직접 실행한다.

```bash
cd /path/to/TradingAgents

# 1) 무거운 langchain류 없이 fastapi/uvicorn만
.venv/bin/pip install --no-deps -e .
.venv/bin/pip install fastapi uvicorn

# 2) API 키 발급 (한 번만)
openssl rand -hex 32
# -> RESEARCH_GATEWAY_API_KEY 값으로 사용

# 3) 서버 실행 (RESEARCH_GATEWAY_API_KEY, TOSS_SECURITIES_CLIENT_ID/SECRET는
#    .env에 이미 있으면 자동으로 로드됨 — tradingagents/__init__.py가 로드)
.venv/bin/python3 scripts/run_service_api.py \
  --host 127.0.0.1 --port 8653 \
  --enable-background-jobs --rankings-poll-interval 300 \
  > /tmp/research_gateway_local.log 2>&1 &

# 4) 외부 노출 (URL은 프로세스 켜져 있는 동안만 유지, 재시작하면 바뀜)
cloudflared tunnel --url http://127.0.0.1:8653 > /tmp/cloudflared_local.log 2>&1 &
grep -o "https://[a-z0-9-]*\.trycloudflare\.com" /tmp/cloudflared_local.log
```

확인:

```bash
curl http://127.0.0.1:8653/healthz
curl -H "Authorization: Bearer <API_KEY>" https://<터널주소>.trycloudflare.com/api/breaking
```

**한계**: 맥이 꺼지거나 재부팅하면 같이 죽는다. 재시작 시 `cloudflared`
URL도 새로 바뀌므로 Supabase `RESEARCH_GATEWAY_URL` 시크릿을 다시
갱신해야 한다. 실제 서비스 단계에선 아래 GCP 방식으로 옮긴다.

## 실제 서비스 단계: GCP e2-micro + Cloudflare Tunnel (월 ~5,500원)

- GCP e2-micro: us-west1/us-east1/us-central1 중 한 리전, 2vCPU 공유/1GB
  RAM/30GB 디스크. 컴퓨트·디스크는 Always Free지만, 외부 IP는 2024년
  정책 변경으로 시간당 $0.005(월 ~$3.65) 과금된다 — 임시/고정 상관없이
  동일 가격이라 고정 IP를 따로 예약할 이유는 없다.
- Cloudflare Tunnel: 무료·무제한, 포트 개방 없이 아웃바운드 연결만으로
  HTTPS 노출.
- Oracle Cloud(Always Free, 스펙은 더 크고 IP도 무료)도 대안이지만
  최근(2026-06) 무예고로 무료 한도를 절반으로 줄인 전례가 있고 리전
  용량 부족으로 프로비저닝이 실패하는 사례가 흔해 후순위로 뒀다.
- **Toss 증권 IP 허용 목록**: VM을 새로 만들면 그 VM의 외부 IP를 Toss
  Open API 콘솔(WTS 로그인 → 설정 → Open API)에 등록해야 한다. 등록
  전에는 `access_denied: IP address not allowed`로 막힌다. VM 외부 IP
  확인은 `curl -s ifconfig.me`.

## 0. 이미지 빌드 & 푸시 (선택 — 검증 안 됨)

아래 Docker 경로는 설계만 해두고 실제로는 안 써봤다. 실제 GCP 배포
때는 이 문서의 "로컬 맥" 섹션과 같은 방식(venv + `pip install --no-deps`)
으로 VM에서 직접 실행했다 — 1GB RAM에서도 문제없이 됐다(빌드가 아니라
설치만 하면 되니까). Docker로 가고 싶으면 아래를 참고하되, e2-micro에서
직접 빌드하지 말고 로컬/CI에서 빌드해서 레지스트리에 올리는 게 안전하다.

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

# 결제 계정 연결은 콘솔에서 (카드 등록 필요). 컴퓨트/디스크는 Always Free지만
# 외부 IP는 월 ~5,500원(~$3.65) 과금된다 — 위 "실제 서비스 단계" 참고.
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
