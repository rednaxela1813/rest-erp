# Roadmap: Restaurant ERP (MVP)

This roadmap defines a **minimal but fully working restaurant ERP system**.

The goal is not to build a "universal ERP", but to implement a **real operational flow**:

> receive goods → sell → deduct stock → accept payment → handle refunds

---

# 0. Goal

The system must support:

1. receiving stock and raw materials
2. tracking accurate inventory balances
3. selling products and menu items
4. deducting stock (directly or via recipes)
5. accepting payments
6. processing refunds

Everything else is out of scope for MVP.

---

# 1. Architecture

## 1.1 System type

* modular monolith
* single repository
* single PostgreSQL database
* Docker-based development

## 1.2 Domains (strict separation)

```text
inventory   → source of truth for stock
recipes     → defines what to deduct
pos         → orders
payments    → money
purchasing  → stock input
orgs        → organization boundaries
catalog     → items and menu
```

---

# 2. Core Invariants

These must never be violated:

### Stock

* stock is tracked only via `StockMovement`
* no direct `stock_qty` as source of truth

### POS

* cannot modify stock directly

### Recipes

* only defines ingredients
* does not perform deductions

### Inventory

* only owner of stock state

### Data ownership

* all data is scoped to `Organization`

---

# 3. Driving Scenarios

Development is driven by real flows.

### Scenario A

> Receive 20 cola cans → sell 2 → remaining stock = 18

### Scenario B

> Sell burger → deduct bun, patty, lettuce, sauce

### Scenario C

> Refund cola → money returned + stock restored

### Scenario D

> Refund burger → money returned, no stock restoration

---

# 4. Development Stages

---

# Stage 0 — Setup

## Goal

Stable development environment.

## Tasks

* Docker works
* database runs
* pytest runs
* CI pipeline works

## Result

Ready for TDD development.

---

# Stage 1 — Organizations

## Models

* Organization
* OrganizationMember

## Rules

* data isolation per organization

## Test

* user A cannot access data of user B

---

# Stage 2 — Catalog

## Models

* Unit
* StockItem
* MenuItem

## Concepts

* stock item → warehouse item
* menu item → sold item

## Test

* create item and menu entity

---

# Stage 3 — Inventory (critical)

## Models

* Warehouse
* StockMovement

## Movement types

* IN
* OUT
* ADJUSTMENT

## Service

* calculate_balance()

## Rules

* cannot deduct more than available
* stock = sum of movements

## Tests

* +10, +5, -3 → 12

---

# Stage 4 — Purchasing

## Models

* Supplier
* GoodsReceipt
* GoodsReceiptLine

## Logic

* draft → no effect
* posted → creates IN movements

## Test

* posted increases stock

---

# Stage 5 — Recipes

## Models

* Recipe
* RecipeLine

## Relations

* MenuItem → Recipe
* RecipeLine → StockItem

## Service

```python
expand_recipe(menu_item)
```

## Test

* burger expands to ingredients

---

# Stage 6 — POS (Orders)

## Models

* Order
* OrderLine

## Statuses

* draft
* submitted
* paid
* cancelled

## Logic

* add items
* calculate total

## Test

* total is correct

---

# Stage 7 — Order Finalization (critical)

## Service

```python
finalize_order(order)
```

## Behavior

* validate stock
* stock item → direct deduction
* menu item → via recipe
* create OUT movements

## Rules

* atomic operation
* no partial deduction

## Test

* insufficient stock → full rollback

---

# Stage 8 — Payments

## Models

* Payment

## Methods

* cash
* card

## Rules

* cannot double-pay
* order and payment states must match

## Test

* payment sets order to paid

---

# Stage 9 — Refunds

## Models

* Refund

## Policies

* cola → return to stock
* burger → no stock return

## Test

* burger refund does not restore stock

---

# Stage 10 — Roles

## Roles

* owner
* manager
* cashier

## Rules

* cashier cannot receive goods
* manager can

---

# 5. Definition of Done

System must support:

* organization
* warehouse
* stock items
* menu items
* recipes
* goods receipt
* order creation
* stock deduction
* payment
* refund

---

# 6. Development Workflow

For each task:

1. define scenario
2. define invariants
3. write failing test
4. implement minimal code
5. refactor

---

# 7. Forbidden Practices

* building UI before domain
* storing stock in fields
* mixing domains
* building universal ERP
* expanding scope early

---

# 8. First Task

Start with:

> receive 10 cola → sell 2 → remaining 8

Then expand step by step.

---

# 9. Summary

You are not building "ERP".

You are building:

> stock movement → sale → money → control

If this works — the system is already valuable.
