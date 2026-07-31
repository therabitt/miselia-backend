#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# File    : scripts/redis-production-config.sh
# Desc    : Konfigurasi Redis untuk production Miselia (Railway / VPS).
#
#           Menerapkan:
#             1. maxmemory-policy → allkeys-lru
#                Saat Redis penuh, key lama dihapus otomatis (LRU).
#                Cocok untuk paper cache yang boleh di-evict jika memory penuh.
#
#             2. maxmemory → 256mb (Railway starter plan)
#                Blueprint §18.3: paper cache + rate limit + Celery queues
#                masuk dalam 256mb di Fase 1. Sesuaikan untuk plan yang lebih besar.
#
#             3. save → disable periodic RDB snapshot
#                Paper cache tidak perlu persistent — Redis restart aman,
#                cache akan di-rebuild otomatis dari API eksternal.
#
#             4. appendonly → no (disable AOF)
#                AOF tidak diperlukan untuk cache-only data.
#                Rate limit state akan reset saat restart — acceptable.
#
#           PRASYARAT:
#             - redis-cli terinstall
#             - REDIS_URL set di environment atau argument pertama
#
#           USAGE:
#             export REDIS_URL=redis://user:pass@host:port
#             bash scripts/redis-production-config.sh
#
#             Atau langsung dengan URL:
#             bash scripts/redis-production-config.sh redis://host:6379
#
# Step    : STEP 14 — DevOps: Env Vars + Redis Config
# Ref     : Blueprint §18.3, PMD Fase 1 §C DevOps
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Resolve Redis URL ──────────────────────────────────────────────────────

REDIS_URL="${1:-${REDIS_URL:-redis://localhost:6379}}"

# Pisahkan host dan port dari URL untuk redis-cli -u
# redis-cli --version ≥ 7 mendukung -u flag langsung
if ! redis-cli --version &>/dev/null; then
  echo "ERROR: redis-cli tidak ditemukan. Install terlebih dahulu."
  exit 1
fi

echo "=== Miselia Redis Production Config ==="
echo "Target: ${REDIS_URL//:*@/@*:}"  # Mask password di log
echo ""

# ── Helper: run redis command ──────────────────────────────────────────────

run_redis() {
  local cmd="$1"
  local expected="$2"

  result=$(redis-cli -u "$REDIS_URL" $cmd 2>&1)

  if [[ "$result" == "$expected" ]]; then
    echo "  ✓ $cmd → $result"
  else
    echo "  ⚠ $cmd → $result (expected: $expected)"
  fi
}

# ── 1. Memory policy: allkeys-lru ─────────────────────────────────────────
echo "[1/4] Setting maxmemory-policy = allkeys-lru"
run_redis "CONFIG SET maxmemory-policy allkeys-lru" "OK"

# ── 2. Memory limit: 256mb ────────────────────────────────────────────────
echo "[2/4] Setting maxmemory = 256mb"
run_redis "CONFIG SET maxmemory 268435456" "OK"  # 256 * 1024 * 1024 bytes

# ── 3. Disable RDB snapshot ───────────────────────────────────────────────
echo "[3/4] Disabling RDB snapshots (paper cache tidak perlu persistent)"
run_redis "CONFIG SET save ''" "OK"

# ── 4. Disable AOF ───────────────────────────────────────────────────────
echo "[4/4] Disabling AOF (appendonly)"
run_redis "CONFIG SET appendonly no" "OK"

echo ""

# ── Verification ──────────────────────────────────────────────────────────
echo "=== Verification ==="

policy=$(redis-cli -u "$REDIS_URL" CONFIG GET maxmemory-policy 2>&1 | tail -1)
memory=$(redis-cli -u "$REDIS_URL" CONFIG GET maxmemory 2>&1 | tail -1)
memory_mb=$((memory / 1024 / 1024))

echo "  maxmemory-policy : $policy"
echo "  maxmemory        : ${memory_mb}mb (${memory} bytes)"
echo ""

# ── Info summary ──────────────────────────────────────────────────────────
redis_version=$(redis-cli -u "$REDIS_URL" INFO server 2>&1 | grep "redis_version" | cut -d: -f2 | tr -d '[:space:]')
used_memory_human=$(redis-cli -u "$REDIS_URL" INFO memory 2>&1 | grep "used_memory_human:" | cut -d: -f2 | tr -d '[:space:]')
connected_clients=$(redis-cli -u "$REDIS_URL" INFO clients 2>&1 | grep "connected_clients:" | cut -d: -f2 | tr -d '[:space:]')

echo "  Redis version    : $redis_version"
echo "  Used memory      : $used_memory_human"
echo "  Connected clients: $connected_clients"
echo ""
echo "✓ Redis production config applied successfully."
echo ""
echo "CATATAN untuk Railway:"
echo "  - Config ini perlu dijalankan ulang setiap kali Redis di-restart"
echo "    karena Railway Redis tidak persist CONFIG SET."
echo "  - Alternatif: set REDIS_ARGS di Railway env untuk persistent config."
echo "  - Untuk Railway managed Redis, hubungi support untuk custom maxmemory."
