# Construction 3IQ Demo

[![Offline tests](https://github.com/Krevetor6962/construction-3iq-demo/actions/workflows/tests.yml/badge.svg)](https://github.com/Krevetor6962/construction-3iq-demo/actions/workflows/tests.yml)

A customer-neutral construction-material supplier demo combining **Fabric IQ principles**, **Foundry IQ policy retrieval**, and **simulated Work IQ collaboration context**.

> We cannot deliver every order in full. Which customer commitments should we protect, what can we safely offer the others, and who needs to act?

The application makes an evidence-backed **proposal**, not an autonomous business decision. It never sends customer emails, approves substitutions, books stock or modifies orders.

![Live experience architecture](docs/architecture/construction-3iq-overview.png)

## What is included

- A local Python web app with a live commitment queue, three evidence lanes, asynchronous orchestration, citations, tool traces and grounded follow-up chat.
- Microsoft Agent Framework orchestration and three versioned Microsoft Foundry prompt specialists.
- Reproducible synthetic data: **100 accounts, 12 products, 200 commitments, 31 tables**, eight policies and 600 collaboration records.
- Native Fabric ontology and GraphModel definitions, Lakehouse/Notebook/Eventhouse deployment scripts, and Bicep for isolated Azure resources.
- A **25-question benchmark**, offline tests, and live acceptance scripts.
- [Architecture diagrams](docs/architecture/rg-construction-3iq-demo-architecture.md), including editable Excalidraw and high-resolution SVG/PNG.
- [A complementary Fabric data-agent preparation kit](docs/data-agent/README.md) with source instructions and 12 GQL/SQL/KQL examples. **No data-agent item is automatically created.**

This public repository contains no live deployment manifest, cloud credentials, personal working-directory paths, or access to the author's Azure/Fabric environment. Cloud identifiers in documentation are placeholders.

## The three lanes

| Lane | Evidence | Important distinction |
| --- | --- | --- |
| Fabric IQ | Native ontology's generated GraphModel, queried using GQL | Default `ontology_graph` mode uses real graph queries, not GraphQL or a claimed native natural-language KB call |
| Foundry IQ | Azure AI Search knowledge base over authenticated file-source policies | Eight synthetic policy documents, with source citations |
| Work IQ - simulated | Scenario-scoped Azure AI Search collaboration records | **Not connected to live Microsoft 365 or the Work IQ service** |

Remote Foundry specialists request a read-only `retrieve_evidence` function. The local application validates that request, queries the configured source using user credentials, and returns the evidence. The final synthesis uses the same `gpt-5.4` deployment.

The reference deployment used direct ontology-graph mode because its native ontology natural-language KB endpoint failed. The optional `native_knowledge_base` mode must be validated in your own environment; there is no silent switch between modes.

## Quick start: offline, no Azure account required

Requirements: **Python 3.11+**. The documented launcher and cloud deployment scripts target Windows/PowerShell.

```powershell
git clone https://github.com/Krevetor6962/construction-3iq-demo.git
Set-Location construction-3iq-demo

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
Copy-Item config\demo-profile.example.json config\demo-profile.json
.\.venv\Scripts\python.exe scripts\generate_data.py
.\scripts\start_demo.ps1
```

Open **http://127.0.0.1:8095** and select **Offline synthetic demo (no cloud calls)**.

The example profile uses zero UUIDs so it can be used offline without publishing or guessing cloud identities. Cloud authentication and provisioning reject these placeholders. The local profile is ignored by Git.

- Offline results are clearly labelled and make no model/cloud calls.
- Live mode is the app's explicit default; without a deployment manifest it displays an actionable error rather than pretending to be live.
- The server binds to loopback only. Do not expose this development server directly to the internet.
- Local jobs and chat state are lost when the server restarts.

## The golden scenario

| Project | Ordered insulation | Proposed allocation |
| --- | ---: | ---: |
| School renovation | 800 m2 | 800 m2 |
| Apartment construction | 600 m2 | 400 m2 |
| Office refurbishment | 400 m2 | 0 m2 |
| **Total** | **1,800 m2** | **1,200 m2** |

At EUR 20/m2, the shortage is **600 m2**, total order value is **EUR 36,000**, and unfilled order value is **EUR 12,000**. Unfilled order value is not realized loss or savings.

Supporting scenarios demonstrate a candidate material requiring human qualification, shared inbound deliveries with different customer deadlines, informal promises conflicting with stock facts, and consent that remains denied even when an allocation is covered.

## Adapt the demo

Copy the [example profile](config/demo-profile.example.json) to `config/demo-profile.json`, edit that ignored local copy, then regenerate the synthetic data:

- `displayName` / `supplierName`: presentation branding.
- `seed`: deterministic data generation.
- `asOfDate`: scenario clock; dates are not interpreted using the presenter's wall clock.
- `currency`: synthetic fixture label, not an exchange-rate conversion.
- `fabricEvidenceMode`: explicitly `ontology_graph` or `native_knowledge_base`.

Do not put real customer documents, personal data, credentials or production connection details into the tracked fixture files.

## Deploy your own isolated Azure/Fabric environment

Deployment incurs costs and is **never run by CI**. Inspect the templates, permissions and target names before approving anything.

1. Install/sign in to Azure CLI and install Bicep separately.
2. Replace `subscriptionId`, `tenantId` and `capacityId` in your ignored profile with your own IDs.
3. Confirm the account can create resources and assign the scoped roles, and that the selected **existing F32** is active and supports the required Fabric features.
4. Confirm model availability/quota and preview support. The current templates use:
   - New Azure resource group `rg-construction-3iq-demo`.
   - Foundry S0/project in `eastus2`.
   - `gpt-5.4` version `2026-03-05`, GlobalStandard, capacity 50.
   - `text-embedding-3-large` version `1`, Standard, capacity 10.
   - Search Basic, one replica/partition, and Storage LRS in `westus3`.
   - New Fabric workspace `Construction 3IQ Demo`, assigned to your selected F32.
5. Run read-only preflight, then explicitly approve your deployment:

```powershell
.\scripts\preflight.ps1

.\scripts\deploy_azure.ps1 `
  -DeployerPrincipalId '<YOUR_ENTRA_OBJECT_ID>' `
  -ApproveProvisioning

.\.venv\Scripts\python.exe scripts\deploy_fabric.py --approve-provisioning
.\.venv\Scripts\python.exe scripts\configure_iq.py --approve
```

The templates currently enforce the reference regions and F32 requirement. If you need other regions/SKUs, deliberately update and revalidate the templates and preflight together; do not assume those settings are universally available.

The scripts write an ignored `config/deployment.json` with actual resource IDs and agent versions. They refuse to silently adopt unowned same-named resources or replace recorded deployment references. No existing shared capacity is automatically resumed, resized or deleted.

### Authentication and network boundaries

- Local runtime uses Azure CLI user credentials; tokens are not stored in the browser or repository.
- Search uses a managed identity for permitted model access.
- Search and Foundry use authenticated public endpoints in this reference topology.
- Storage has anonymous/public-network/shared-key access disabled. It is provisioned but is **not the active policy ingestion path**.
- Policies use the supported authenticated Search **file** knowledge source, avoiding a requirement for local public Blob access. Do not weaken tenant policies to make a sample deploy.
- Native ontology KB mode requires separate delegated authorization and successful retrieval checks. Direct graph mode does not claim that this endpoint ran.

### Cost

The reference pricing lookup for one Search Basic unit was approximately **USD 0.101/hour** (USD 73.73 at 730 hours). Recheck current regional pricing. Model inference, embeddings, retrieval, storage/operations, transfer and the shared Fabric capacity are additional.

No Azure-hosted web app, container registry, live Microsoft 365 connector or new Fabric capacity is provisioned.

## Validate

Offline:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\run_benchmark.py --mode offline
```

After deploying and starting the local app:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_fabric.py
.\.venv\Scripts\python.exe scripts\run_benchmark.py --mode live
.\.venv\Scripts\python.exe scripts\smoke_app.py --mode live
```

Live validation generates usage charges. Results are saved under ignored `tests/results/`. Use `--resume` with the benchmark to revalidate existing results and retry only failed/incomplete cases, preserving failed attempts.

The original reference environment passed all 25 live cases in explicit graph mode and three live API/browser journeys. Those environment-specific results are not shipped as proof that your deployment is working. CI validates **offline behavior only**, with no Azure secrets.

## Presenter flow

1. Select the school-insulation commitment and explain the stock shortage.
2. Hover/focus the info icon beside **Customer commitments** to inspect the exact GQL used by the live queue.
3. Run the proposal; show the three evidence lanes and scoped citations.
4. Ask which other customers share the stock, what qualification is missing, or who owns the next step.
5. Request a customer-safe draft; make clear it has not been sent or approved.
6. Inspect the trace to distinguish real cloud retrieval from offline fixtures.

For a deeper graph story, use the [data-agent preparation kit](docs/data-agent/README.md), including its nine-edge profile-to-other-customer path.

## Repository map

| Folder | Contents |
| --- | --- |
| `src/construction_iq` | Configuration, generator, query clients, orchestration and source contracts |
| `apps/construction-command-center` | Local HTTP server and static UI |
| `infra` | Azure Bicep templates |
| `scripts` | Generation, preflight, deployment and validation entry points |
| `data/construction_synthetic` | Reproducible synthetic CSV/JSON fixtures |
| `knowledge` | Synthetic policy and collaboration corpus |
| `ontology` | Construction entity/relationship model |
| `docs` | Architecture and Fabric data-agent preparation |
| `tests` | Offline regression tests and benchmark questions |

## Publication and cleanup

Your local profile, deployment manifests, live results, virtual environments and secret files are ignored by Git. Inspect staged files before publishing any customization. No workflow deploys cloud resources or submits business actions.

Cleanup is deliberate: inspect the IDs in your own deployment manifest and delete only resources you own. Fabric workspace cleanup is separate from Azure resource-group cleanup. **Never delete or pause a shared Fabric capacity as part of demo cleanup.**

## License and icon attribution

Project code is under the [MIT license](LICENSE). Original Microsoft Fabric icons retain their [Microsoft license notice](docs/architecture/icons/LICENSE-Microsoft.txt) and [source attribution](docs/architecture/icons/README.md). The illustrative icons are not claims of additional deployed services.

Microsoft Fabric, Foundry and other product names are used descriptively; this community demo is not an official Microsoft product or production reference architecture.
