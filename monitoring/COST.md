# S10 cost — what your stack costs, and where to read it

Two separate numbers, from two separate places. Never add them together without saying so.

| Number | Where it lives | Who reads it | Moves with |
|---|---|---|---|
| **Your LLM spend** | the professor's central gateway, your key's row (`dbai-<your id>`) | projected by the professor | chat (`course-chat`) and embedding calls, at **notional** course prices: the gateway's provider (nan.builders) is flat-rate, so these are course accounting, not a real bill |
| **Your AWS cost** | the AWS account (Cost Explorer / Budgets) | **[controller]** your laptop, with the temporary sandbox session | VM hours, disk, public IPv4 |

Your Prometheus cannot show either one: the gateway is outside your cluster, and billing is
not a metric your cluster exposes.

## 1. Your gateway spend (projected view)

The professor projects the per-key view (a sorted grid, one card per student id). Find
**your id** and write down **both** numbers in `JOURNAL.md`:

- the amount on your card, e.g. `$0.000670`;
- the **timestamp in the page header** (`generated … UTC`).

The page shows labels only, never keys. Spend appears ~6–14 s after a call, and the page
reloads every 30 s, so after the LOAD FEST give it about a minute.

## 2. Your AWS month-to-date cost — [controller]

On the **laptop controller** (not the VM), with the temporary sandbox session. The end
date is **exclusive**, so use tomorrow:

```bash
aws ce get-cost-and-usage \
  --time-period "Start=$(date -u +%Y-%m-01),End=$(date -u -d tomorrow +%Y-%m-%d)" \
  --granularity MONTHLY --metrics UnblendedCost \
  --query 'ResultsByTime[0].Total.UnblendedCost'
#   macOS: End=$(date -u -v+1d +%Y-%m-%d)
```

And the budget (**$25/month, email at 80 % of ACTUAL**):

```bash
aws budgets create-budget --account-id <ACCOUNT_ID> \
  --budget 'BudgetName=dbai-monthly,BudgetLimit={Amount=25,Unit=USD},TimeUnit=MONTHLY,BudgetType=COST' \
  --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"<your email>"}]}]'
```

(Console equivalent: Billing and Cost Management → Budgets → Create budget → Monthly cost
budget → $25 → alert at 80 % of actual → your email.)

### Sandbox permission result (qualified 2026-09-24): the student session is denied

In the ESADE Innovation Sandbox the **student role `esadeis_IsbUsersPS` is denied all of
this**:

- CLI `ce:GetCostAndUsage` → `AccessDeniedException`;
- `budgets:ModifyBudget`/`ViewBudget` → `AccessDeniedException`;
- console Cost Explorer → "Access denied";
- console Budgets → "You don't have permission to access billing information".

**Fallback used in class:** the professor runs the same command and creates/shows the
same $25 / 80 % budget with the **manager** session and projects both. Verified on
2026-09-24: CLI month-to-date `2.0126742851 USD`, the budget created with an `ACTUAL 80`
notification and then deleted, and the console Cost Explorer and Budgets both working. You
record the projected month-to-date figure and its time. You **do not** claim that you created a
budget. If the sandbox later grants `ce:GetCostAndUsage` and `budgets:*` to the student role,
the commands above are the student path unchanged.

## 3. An alert is not a brake

- A Budget alert **only sends an email**. It never stops, caps or deletes anything. Stopping
  spend is **your** action.
- From S8 on, **stop the VM whenever you are not working** — [controller]:
  `dbai/console.sh stop <env-id>` (`start` to resume; same disk, same IP).
- A **stopped** VM still costs money: the EBS disk and the public IPv4 address are billed
  while stopped (AWS charges idle public IPv4 too). Only `dbai/console.sh final-cleanup <env-id> --confirm`
  stops everything. Do it at the end of the course, after your evidence is safe.

### Illustrative prices (eu-west-1, AWS Price List API, 2026-09-24): refresh before teaching

| Item | Price | Month |
|---|---|---|
| `t3.large` on-demand, 24/7 | $0.0912/h | ≈ $66.6 |
| same, running ~45 h/week only | | ≈ $17.8 |
| EBS gp3 30 GB (billed while stopped) | $0.088/GB-month | ≈ $2.64 |
| public IPv4 (in use **or idle**) | $0.005/h | ≈ $3.65 |
| your gateway key | professor-capped | $5 / 30 days max |

Refresh the rates on the controller (manager session):

```bash
aws pricing get-products --region us-east-1 --service-code AmazonEC2 \
  --filters Type=TERM_MATCH,Field=instanceType,Value=t3.large Type=TERM_MATCH,Field=location,Value="EU (Ireland)" \
            Type=TERM_MATCH,Field=operatingSystem,Value=Linux Type=TERM_MATCH,Field=tenancy,Value=Shared \
            Type=TERM_MATCH,Field=preInstalledSw,Value=NA Type=TERM_MATCH,Field=capacitystatus,Value=Used
```
