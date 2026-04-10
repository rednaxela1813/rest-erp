# Operations Guide: Offline Payments & Fiscalization

Этот документ — операционный гайд для кассира и администратора при временных проблемах связи (банк/терминал/еKasa).
Он дополняет техническое описание в README и описывает практические шаги.

---

## 1) Когда применять

Сценарии:
- терминал банка не отвечает (timeout)
- eKasa недоступна (фискализация не проходит)
- интернет нестабилен (частые обрывы, задержки)

---

## 2) Что считается «нормальным» состоянием

- Платеж: `status=captured`, `capture_status=confirmed`
- Фискализация: `fiscal_status=confirmed`
- Команды устройства: есть ACK по фискальной команде

---

## 3) Действия кассира при сбое

### 3.1 Терминал банка не отвечает
1) Убедись, что запрос на оплату создан (чек в POS виден).
2) Отметь вручную факт попытки оплаты (по чеку терминала, если он печатался).
3) Сообщи администратору: нужен ручной reconcile/override.

### 3.2 eKasa недоступна
1) Проверь, что заказ проведен в POS (статус платежа есть).
2) Зафиксируй факт продажи (заказ, сумма).
3) Дождись восстановления связи: администратор запустит reconcile или ручной override.

---

## 4) Действия администратора (операционные)

### 4.1 Проверка статуса платежа через API
```
GET /api/v1/payments/<payment_public_id>/status/
```
Поля:
- `capture_status` — состояние capture у банка
- `fiscal_status` — состояние фискализации
- `device_command_counts` — статистика по командам устройств

### 4.2 Ручной override через API (admin/owner)
```
POST /api/v1/payments/<payment_public_id>/manual-resolution/
Content-Type: application/json

{
  "capture_status": "confirmed",
  "fiscal_status": "failed",
  "failure_reason": "manual_override"
}
```
Использовать только после фактической проверки (чек терминала, бумажный лог, подтверждение от банка).

---

## 5) Действия администратора (через Django Admin)

В админке `OrderPayment` доступны действия:
- Mark capture confirmed / timeout
- Mark fiscal confirmed / failed

Использовать для корректировки после проверки.

---

## 6) Reconcile-задачи (операционные)

Если связь восстановилась:
1) Запустить reconcile capture (проверка у провайдера):
   ```python
   from apps.payments.tasks import reconcile_payment_capture
   reconcile_payment_capture.delay(payment.id)
   ```
2) Запустить reconcile fiscal:
   ```python
   from apps.payments.tasks import reconcile_payment_fiscal_status
   reconcile_payment_fiscal_status.delay(payment.id)
   ```

---

## 6.1 Автоматическая отправка неотправленных чеков

В системе настроена периодическая задача Celery Beat:
- каждые 60 секунд отправляет все неотправленные device‑команды в Redis Stream
- это позволяет догонять чеки после восстановления интернета

Если чеки не уходят:
- проверь, что запущены `celery_worker` и `celery_beat`
- проверь доступность Redis

---

## 7) Локальный агент и Redis Stream

Команды устройств стримятся в Redis Stream:
- `DEVICE_COMMANDS_STREAM` (по умолчанию `device_commands`)
Если агент не получает команды — проверь:
- доступность Redis
- наличие задач Celery worker

---

## 8) Контроль и алерты (рекомендуется)

Минимальный checklist:
- Есть ли платежи с `capture_status=timeout`
- Есть ли `fiscal_status=failed` или `pending` более X минут
- Есть ли команды устройств со статусом `failed` с большим числом retry

---

## 9) Политики безопасности (рекомендовано)

- Ручной override выполнять только после фактического подтверждения оплаты.
- Все override фиксировать в `failure_reason`.
- При долгих сбоях — остановить прием безналичных платежей до восстановления связи.
