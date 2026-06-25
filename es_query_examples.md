# CDGC Internal Elasticsearch Query Examples

Reference queries for the `internal_search` tool, which calls
`/ccgf-searchv2/api/v1/search` with `X-INFA-SEARCH-LANGUAGE: elasticsearch`.

**Response structure:** Results are in `hits.hits[]`. Each hit has:
- `_source.core.identity` — the asset's internal UUID
- `_source.core.name` — display name
- `_source.core.classType` — asset type
- `_source.elementType` — `OBJECT` or `RELATIONSHIP`

**Format rules:**
- Every query body is a JSON object passed as `body` to `internal_search`.
- Always include `"elementType": ["OBJECT"]` in `must` unless explicitly searching relationships.
- Use `filter` (not `must`) for classType/lifecycle filters — it's faster (no scoring).
- `from` + `size` control pagination. Max `size` is typically 10000.
- Results are deduplicated by `core.identity` — no need to worry about duplicates.

**COMMON MISTAKE — `core.resourceName` does NOT exist on asset objects.**
To find assets from a named catalog source (e.g. "NSEN Snowflake Retail Marketing"):
1. Call `find_catalog_sources_by_type` or `list_catalog_sources` to get the source `id`
2. Use that `id` as `core.origin` in the filter (see example 12)
Never use `core.resourceName` as a filter — it will return 0 results every time.

---

## 1. Fetch multiple assets by ID (bulk fetch)

**Use this instead of calling `get_asset` in a loop.** Returns full `_source` for each asset.

```json
{
  "from": 0,
  "size": 100,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["OBJECT"] } },
        { "terms": { "core.identity": ["uuid-1", "uuid-2", "uuid-3"] } }
      ]
    }
  }
}
```

---

## 2. Find all Critical Data Elements (CDEs)

Returns Business Terms flagged as CDEs (`isCDE = true`).

```json
{
  "from": 0,
  "size": 500,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["OBJECT"] } },
        { "term": { "com.infa.ccgf.models.governance.isCDE": true } }
      ],
      "filter": [
        { "terms": { "core.classType": ["com.infa.ccgf.models.governance.BusinessTerm"] } }
      ]
    }
  },
  "sort": [{ "core.name": { "order": "asc" } }]
}
```

---

## 3. Find DQ Rule Occurrences with unacceptable scores

```json
{
  "from": 0,
  "size": 200,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["OBJECT"] } }
      ],
      "filter": [
        { "terms": { "core.classType": ["com.infa.ccgf.models.governance.RuleInstance"] } },
        { "term": { "com.infa.ccgf.models.governance.thresholdResult": "not acceptable" } }
      ]
    }
  },
  "sort": [{ "com.infa.ccgf.models.governance.value": { "order": "asc" } }]
}
```

---

## 4. Find all DQ Rule Templates

```json
{
  "from": 0,
  "size": 500,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        { "terms": { "core.classType": ["com.infa.ccgf.models.governance.RuleTemplate"] } }
      ]
    }
  },
  "sort": [{ "core.name": { "order": "asc" } }]
}
```

---

## 5. Find all Business Terms (optionally by domain or policy)

All Business Terms:
```json
{
  "from": 0,
  "size": 1000,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        { "terms": { "core.classType": ["com.infa.ccgf.models.governance.BusinessTerm"] } }
      ]
    }
  },
  "sort": [{ "core.name": { "order": "asc" } }]
}
```

---

## 6. Find all Policies

```json
{
  "from": 0,
  "size": 500,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        { "terms": { "core.classType": ["com.infa.ccgf.models.governance.Policy"] } }
      ]
    }
  },
  "sort": [{ "core.name": { "order": "asc" } }]
}
```

---

## 7. Find all Classifications (DataElement and DataEntity)

```json
{
  "from": 0,
  "size": 500,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        {
          "terms": {
            "core.classType": [
              "core.DataElementClassification",
              "core.DataEntityClassification"
            ]
          }
        }
      ]
    }
  },
  "sort": [{ "core.name": { "order": "asc" } }]
}
```

---

## 8. Find Business Term ↔ Technical Asset relationships (glossary links)

Returns all relationships linking Business Terms to technical assets (columns, tables, etc.).
Relationship type: `com.infa.ccgf.models.governance.IClassTechnicalGlossaryBase`

```json
{
  "from": 0,
  "size": 10000,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["RELATIONSHIP"] } },
        { "terms": { "type": ["com.infa.ccgf.models.governance.IClassTechnicalGlossaryBase"] } }
      ]
    }
  }
}
```

Each hit has `_source.core.sourceIdentity` (technical asset) and `_source.core.targetIdentity` (Business Term).

---

## 9. Find Classification ↔ Asset relationships

Returns all `core.ClassifiedAs` relationships (which assets have which classifications).

```json
{
  "from": 0,
  "size": 10000,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["RELATIONSHIP"] } },
        { "terms": { "type": ["core.ClassifiedAs"] } }
      ]
    }
  }
}
```

---

## 10. Find Policy ↔ Classification relationships

```json
{
  "from": 0,
  "size": 5000,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["RELATIONSHIP"] } },
        { "terms": { "type": ["com.infa.ccgf.models.governance.relatedPolicyClassification"] } }
      ]
    }
  }
}
```

---

## 11. Find Policy ↔ Business Term relationships

```json
{
  "from": 0,
  "size": 5000,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["RELATIONSHIP"] } },
        { "terms": { "type": ["com.infa.ccgf.models.governance.relatedBusinessTermPolicy"] } }
      ]
    }
  }
}
```

---

## 12. Find all assets from a specific catalog source (by origin UUID)

**CRITICAL:** Individual assets do NOT have a `core.resourceName` field — do not filter by it.
Assets are linked to their catalog source via `core.origin` (a UUID).

**Two-step process to find assets by source name:**
1. Call `find_catalog_sources_by_type` or `list_catalog_sources` to find the source by name → get its `id`
2. Use that `id` as the `core.origin` value below

Each catalog source has an `origin` UUID. Use this to get all assets scanned from it.

```json
{
  "from": 0,
  "size": 10000,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        { "terms": { "core.origin": ["catalog-source-origin-uuid-here"] } }
      ]
    }
  }
}
```

Add a classType filter to narrow to tables only:
```json
{
  "filter": [
    { "terms": { "core.origin": ["catalog-source-origin-uuid-here"] } },
    { "terms": { "core.classType": ["com.infa.odin.models.relational.Table"] } }
  ]
}
```

---

## 13. Find all relationships targeting a specific asset (incoming)

```json
{
  "from": 0,
  "size": 250,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["RELATIONSHIP"] } },
        { "terms": { "core.targetIdentity": ["target-asset-uuid-here"] } }
      ]
    }
  }
}
```

For outgoing (what this asset points TO), use `core.sourceIdentity` instead.

---

## 14. Find assets by name (text search)

Full-text search (partial match):
```json
{
  "from": 0,
  "size": 50,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["OBJECT"] } },
        { "match": { "core.name": "customer" } }
      ]
    }
  }
}
```

Exact name match:
```json
{ "term": { "core.name.keyword": "CUSTOMER_ID" } }
```

---

## 15. Find assets modified recently

```json
{
  "from": 0,
  "size": 100,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["OBJECT"] } },
        { "range": { "core.modifiedOn": { "gte": "now-7d/d" } } }
      ]
    }
  },
  "sort": [{ "core.modifiedOn": { "order": "desc" } }]
}
```

---

## 16. Find all Catalog Sources (Resources)

```json
{
  "from": 0,
  "size": 500,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        { "terms": { "core.classType": ["core.Resource"] } }
      ]
    }
  },
  "sort": [{ "core.name": { "order": "asc" } }]
}
```

---

## 17. Find published Asset Groups

```json
{
  "from": 0,
  "size": 10000,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        { "terms": { "core.classType": ["core.AssetGroup"] } },
        { "terms": { "core.assetLifecycle": ["Published"] } }
      ]
    }
  },
  "sort": [{ "core.name": { "order": "asc" } }]
}
```

---

## 18. Find Databricks notebooks

```json
{
  "from": 0,
  "size": 200,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        {
          "terms": {
            "core.classType": [
              "com.infa.odin.models.Databricks.NotebookDefinition",
              "com.infa.odin.models.Databricks.NotebookInstance"
            ]
          }
        }
      ]
    }
  }
}
```

---

## 19. Find Power BI reports and datasets

```json
{
  "from": 0,
  "size": 200,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        {
          "terms": {
            "core.classType": [
              "com.infa.odin.models.PowerBI.Cloud.Report",
              "com.infa.odin.models.PowerBI.Cloud.Dataset",
              "com.infa.odin.models.PowerBI.Cloud.Workspace"
            ]
          }
        }
      ]
    }
  }
}
```

---

## 20. Find Tableau dashboards and workbooks

```json
{
  "from": 0,
  "size": 200,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        {
          "terms": {
            "core.classType": [
              "com.infa.odin.models.Tableau.Dashboard",
              "com.infa.odin.models.Tableau.Workbook",
              "com.infa.odin.models.Tableau.Worksheet"
            ]
          }
        }
      ]
    }
  }
}
```

---

## 21. Find Data Lineage flows (DataSetDataFlow)

```json
{
  "from": 0,
  "size": 5000,
  "query": {
    "bool": {
      "must": [
        { "terms": { "elementType": ["RELATIONSHIP"] } },
        { "terms": { "type": ["core.DataSetDataFlow"] } }
      ]
    }
  }
}
```

For column-level lineage use `core.DirectionalDataFlow`.

---

## 22. Find Marketplace Data Collections and Categories

```json
{
  "from": 0,
  "size": 200,
  "query": {
    "bool": {
      "must": [{ "terms": { "elementType": ["OBJECT"] } }],
      "filter": [
        {
          "terms": {
            "core.classType": [
              "com.infa.cdmp.marketplace.DataCollection",
              "com.infa.cdmp.marketplace.Category",
              "com.infa.cdmp.marketplace.DataAsset"
            ]
          }
        }
      ]
    }
  }
}
```

---

## Complete classType Reference

### Governance & Glossary
| Display Name | classType |
|---|---|
| Business Term | `com.infa.ccgf.models.governance.BusinessTerm` |
| Domain | `com.infa.ccgf.models.governance.Domain` |
| Sub-Domain | `com.infa.ccgf.models.governance.SubDomain` |
| Policy | `com.infa.ccgf.models.governance.Policy` |
| Process | `com.infa.ccgf.models.governance.Process` |
| DQ Rule Template | `com.infa.ccgf.models.governance.RuleTemplate` |
| DQ Rule Occurrence / Instance | `com.infa.ccgf.models.governance.RuleInstance` |
| DQ Result | `com.infa.ccgf.models.governance.DQResult` |
| DQ Profile Run | `com.infa.ccgf.models.governance.DQProfileRun` |
| Issue | `com.infa.ccgf.models.issueManagement.Issue` |

### Classifications
| Display Name | classType |
|---|---|
| Data Element Classification | `core.DataElementClassification` |
| Data Entity Classification | `core.DataEntityClassification` |
| Classified As (relationship) | `core.ClassifiedAs` |

### Technical / Relational
| Display Name | classType |
|---|---|
| Database | `com.infa.odin.models.relational.Database` |
| Schema | `com.infa.odin.models.relational.Schema` |
| Table | `com.infa.odin.models.relational.Table` |
| View | `com.infa.odin.models.relational.View` |
| Column | `com.infa.odin.models.relational.Column` |
| View Column | `com.infa.odin.models.relational.ViewColumn` |
| Primary Key | `com.infa.odin.models.relational.PrimaryKey` |
| Stored Procedure Definition | `com.infa.odin.models.relational.ProcedureDefinition` |
| Stored Procedure Instance | `com.infa.odin.models.relational.ProcedureInstance` |
| Statement | `com.infa.odin.models.relational.Statement` |
| Result Set | `com.infa.odin.models.relational.ResultSet` |

### Databricks
| Display Name | classType |
|---|---|
| Notebook Definition | `com.infa.odin.models.Databricks.NotebookDefinition` |
| Notebook Instance | `com.infa.odin.models.Databricks.NotebookInstance` |
| Folder | `com.infa.odin.models.Databricks.Folder` |
| Command | `com.infa.odin.models.Databricks.Command` |
| Calculation | `com.infa.odin.models.Databricks.Calculation` |

### Power BI
| Display Name | classType |
|---|---|
| Workspace | `com.infa.odin.models.PowerBI.Cloud.Workspace` |
| Dataset | `com.infa.odin.models.PowerBI.Cloud.Dataset` |
| Report | `com.infa.odin.models.PowerBI.Cloud.Report` |
| Field | `com.infa.odin.models.PowerBI.Cloud.Field` |
| Dataset Table | `com.infa.odin.models.PowerBI.Cloud.DatasetTable` |

### Tableau
| Display Name | classType |
|---|---|
| Server | `com.infa.odin.models.Tableau.Server` |
| Site | `com.infa.odin.models.Tableau.Site` |
| Project | `com.infa.odin.models.Tableau.Project` |
| Workbook | `com.infa.odin.models.Tableau.Workbook` |
| Dashboard | `com.infa.odin.models.Tableau.Dashboard` |
| Worksheet | `com.infa.odin.models.Tableau.Worksheet` |
| Data Source | `com.infa.odin.models.Tableau.DataSource` |
| Calculation | `com.infa.odin.models.Tableau.Calculation` |

### IICS (Informatica Cloud Mappings)
| Display Name | classType |
|---|---|
| Project | `com.infa.odin.models.IICS.V2.Project` |
| Folder | `com.infa.odin.models.IICS.V2.Folder` |
| Mapping | `com.infa.odin.models.IICS.V2.Mapping` |
| Mapping Task | `com.infa.odin.models.IICS.V2.MappingTask` |
| Mapping Task Instance | `com.infa.odin.models.IICS.V2.MappingTaskInstance` |
| Calculation | `com.infa.odin.models.IICS.V2.Calculation` |

### File / Storage
| Display Name | classType |
|---|---|
| File System Folder | `com.infa.odin.models.file.Folder` |
| File | `com.infa.odin.models.file.File` |
| Flat File | `com.infa.odin.models.file.flat.FlatFile` |
| Flat Field | `com.infa.odin.models.file.flat.FlatField` |
| Hierarchical File | `com.infa.odin.models.file.hierarchical.HierarchicalFile` |
| Hierarchical Field | `com.infa.odin.models.file.hierarchical.HierarchicalField` |
| Azure Blob Container | `com.infa.odin.models.file.azureblob.Container` |
| Azure Storage Account | `com.infa.odin.models.file.azureblob.StorageAccount` |
| Lakehouse Table | `com.infa.odin.models.lakehouse.LakehouseTable` |

### Messaging / Streaming
| Display Name | classType |
|---|---|
| Kafka Cluster | `com.infa.odin.models.messaging.kafka.Cluster` |
| Kafka Topic | `com.infa.odin.models.messaging.kafka.Topic` |
| Message Field | `com.infa.odin.models.messaging.Field` |

### SSIS
| Display Name | classType |
|---|---|
| Package | `com.infa.odin.models.SSIS.Package` |
| Data Task | `com.infa.odin.models.SSIS.DataTask` |
| Calculation | `com.infa.odin.models.SSIS.Calculation` |

### Data Marketplace (CDMP)
| Display Name | classType |
|---|---|
| Category | `com.infa.cdmp.marketplace.Category` |
| Data Collection | `com.infa.cdmp.marketplace.DataCollection` |
| Data Asset | `com.infa.cdmp.marketplace.DataAsset` |
| Data Element | `com.infa.cdmp.marketplace.DataElement` |
| Order | `com.infa.cdmp.marketplace.Order` |
| Consumer Access | `com.infa.cdmp.marketplace.ConsumerAccess` |
| Delivery Target | `com.infa.cdmp.marketplace.DeliveryTarget` |
| Delivery Template | `com.infa.cdmp.marketplace.DeliveryTemplate` |
| Delivery Format | `com.infa.cdmp.marketplace.DeliveryFormat` |
| Delivery Method | `com.infa.cdmp.marketplace.DeliveryMethod` |
| Terms of Use | `com.infa.cdmp.marketplace.TermsOfUse` |
| Usage Context | `com.infa.cdmp.marketplace.UsageContext` |
| Metric | `com.infa.cdmp.marketplace.Metric` |

### Core / Platform
| Display Name | classType |
|---|---|
| Resource (Catalog Source) | `core.Resource` |
| Data Set | `core.DataSet` |
| Data Element | `core.DataElement` |
| Data Source | `core.DataSource` |
| Asset Group | `core.AssetGroup` |
| Stakeholder | `core.Stakeholder` |
| Certification | `core.supplement.Certification` |
| User Interaction | `core.supplement.UserInteraction` |
| Rating | `core.supplement.Rating` |
| MAC Policy | `core.accesscontrol.IAccessControlPolicy` |

### Custom / API
| Display Name | classType |
|---|---|
| Custom API | `custom.api.API` |
| Custom Data Field | `custom.api.DataField` |

---

## Key Relationship Types Reference

| Relationship | Meaning |
|---|---|
| `com.infa.ccgf.models.governance.IClassTechnicalGlossaryBase` | Business Term linked to technical asset |
| `com.infa.ccgf.models.governance.relatedBusinessTermPolicy` | Policy linked to Business Term |
| `com.infa.ccgf.models.governance.relatedPolicyClassification` | Policy linked to Classification |
| `core.ClassifiedAs` | Asset classified with a Classification |
| `core.DataSetDataFlow` | Table/dataset-level lineage |
| `core.DirectionalDataFlow` | Column-level lineage |
| `core.IClassStakeholder` | Stakeholder assignment to asset |
| `core.DataSetToDataElementParentship` | Table → Column parent/child |
| `core.ResourceParentChild` | Catalog source hierarchy |
| `com.infa.odin.models.relational.TableToColumn` | Table → Column |
| `com.infa.odin.models.relational.SchemaToTable` | Schema → Table |
| `com.infa.odin.models.relational.DatabaseToSchema` | Database → Schema |
| `com.infa.odin.models.PowerBI.Cloud.WorkspaceToDataset` | Power BI Workspace → Dataset |
| `com.infa.odin.models.PowerBI.Cloud.WorkspaceToReport` | Power BI Workspace → Report |
| `com.infa.odin.models.Databricks.FolderToNotebookDefinition` | Databricks Folder → Notebook |
| `com.infa.ccgf.models.governance.asscProfileRunToRuleInstance` | DQ Profile Run → Rule Instance |
| `com.infa.cdmp.marketplace.asscDataCollectionToDataAsset` | Marketplace Collection → Data Asset |
| `core.Join` | Join relationship between datasets |
| `core.Similarity` | Similarity relationship |
