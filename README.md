# Карасов Маркетинг — лендинги

Публичные лендинги. Деплой на **karasov-work.ru** через git-pull (relay тянет, US только push).

- `audit/` — бесплатный экспресс-аудит воронки → https://karasov-work.ru/audit/
- `direkt/` — настройка Яндекс Директа под ключ → https://karasov-work.ru/direkt/
- `_receiver/` — приёмник лида для relay (в веб не отдаётся).

Публикация: US собирает → `git push` → relay `git pull` (cron ~2 мин) → отдаёт локально с RF-edge.
