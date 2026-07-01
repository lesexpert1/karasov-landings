#!/usr/bin/env bash
# Настройка git-pull лендингов на relay (RUVDS). Идемпотентно.
# Запуск на relay под root:
#   curl -fsSL https://raw.githubusercontent.com/lesexpert1/karasov-landings/main/_deploy/setup-relay.sh | bash
set -e
REPO_URL="https://github.com/lesexpert1/karasov-landings.git"
DEST="/var/www/landings"

echo "[1/4] git…"
command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git; }

echo "[2/4] клон/обновление репозитория…"
if [ -d "$DEST/.git" ]; then git -C "$DEST" pull -q; else git clone -q "$REPO_URL" "$DEST"; fi
git config --global --add safe.directory "$DEST" 2>/dev/null || true
chmod -R a+rX "$DEST"
echo "    audit/: $(ls "$DEST/audit" 2>/dev/null | tr '\n' ' ')"

echo "[3/4] nginx: location /audit/…"
CONF=$(grep -rl "server_name .*karasov-work\.ru" /etc/nginx/sites-available/ /etc/nginx/conf.d/ 2>/dev/null | head -1)
[ -n "$CONF" ] || { echo "    ОШИБКА: не нашёл конфиг karasov-work.ru"; exit 1; }
echo "    конфиг: $CONF"
cp "$CONF" "$CONF.bak"
python3 - "$CONF" <<'PY'
import sys,re
p=sys.argv[1]; s=open(p).read()
if '/audit/' not in s:
    block=('    location /audit/ {\n'
           '        alias /var/www/landings/audit/;\n'
           '        index index.html;\n'
           '    }\n\n')
    s=re.sub(r'(\n[ \t]*location\s+/\s*\{)', '\n'+block+r'\1', s, count=1)
    open(p,'w').write(s); print("    /audit/ добавлен")
else:
    print("    /audit/ уже был")
PY
if nginx -t 2>/tmp/ngt.log; then systemctl reload nginx && echo "    nginx перезагружен ✅"; else echo "    nginx -t ОШИБКА → откат:"; cat /tmp/ngt.log; cp "$CONF.bak" "$CONF"; exit 1; fi

echo "[4/4] cron авто-pull (каждые 2 мин)…"
( crontab -l 2>/dev/null | grep -v 'var/www/landings'; \
  echo '*/2 * * * * cd /var/www/landings && /usr/bin/git pull -q >> /var/log/landings-pull.log 2>&1' ) | crontab -

echo ""
echo "=== ПРОВЕРКА ==="
curl -s https://karasov-work.ru/audit/ | grep -o "<title>[^<]*</title>" || echo "  (title не найден — проверь вручную)"
echo "Готово. Открой без ВПН: https://karasov-work.ru/audit/"
