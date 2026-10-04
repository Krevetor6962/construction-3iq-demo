# Architecture icon sources

The original Microsoft Fabric icons in this folder are copied without artwork changes from the [official Fabric icon download](https://github.com/microsoft/fabric-samples/blob/main/docs-samples/Icons.zip), package `@fabric-msft/svg-icons` v6.1.0.

[Microsoft's icon guidance and permitted architecture-documentation usage](https://learn.microsoft.com/en-us/fabric/fundamentals/icons) applies. The package's [MIT license notice](LICENSE-Microsoft.txt) is preserved.

| Asset | Used for |
| --- | --- |
| `fabric_48_color.svg` | Fabric workspace heading |
| `lakehouse_64_item.svg` | Lakehouse |
| `notebook_64_item.svg` | Ingestion notebook |
| `event_house_64_item.svg` | Eventhouse |
| `kql_database_64_item.svg` | Populated KQL database |
| `graph_model_instance_64_item.svg` | Ontology-generated GraphModel |
| `data_agent_64_item.svg` | Prepared-only Fabric data agent, still explicitly marked not deployed |

The official icons are displayed with their original proportions, orientation and colours. They are embedded in both SVG and Excalidraw outputs, so the deliverables do not depend on a remote icon service.

The following are original, generic illustrative symbols, **not official Microsoft product icons**:

- `ontology-symbol.svg`: connected business entities, used because the downloaded collection has no dedicated ontology icon.
- `sql-endpoint-symbol.svg`: a SQL analytics endpoint, not a separately deployed SQL Database.
- `policy-knowledge-symbol.svg`: cited written policy.
- `synthetic-work-symbol.svg`: synthetic people/context, not a live Work IQ or Microsoft 365 connection.

These illustrative symbols do not alter the architecture or imply that another product has been deployed.
