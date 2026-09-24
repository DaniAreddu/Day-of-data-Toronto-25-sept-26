-- Source contract: returns (on-premises SQL Server representation).
--
-- Synthetic, production-inspired scenario. It does not represent a real customer deployment.
-- No SQL Server instance is required: sample-data/sql-server/returns.*.csv are synthetic
-- replication extracts that conform to this contract.
--
-- Contract: contracts/returns.contract.yml (version 1.0.0)
-- Grain:    one row per return
-- All timestamps are UTC.

CREATE TABLE dbo.returns
(
    return_id            varchar(20)    NOT NULL,  -- business key, e.g. RMA-000001
    order_id             varchar(20)    NOT NULL,  -- must reference sales.orders.order_id
    return_timestamp_utc datetime2(0)   NOT NULL,
    return_amount        decimal(12, 2) NOT NULL,  -- in currency_code of the original order
    currency_code        char(3)        NOT NULL,
    return_reason        varchar(40)    NOT NULL,
    source_updated_at    datetime2(0)   NOT NULL,
    ingested_at          datetime2(0)   NOT NULL,  -- when the replication extract landed (UTC)
    CONSTRAINT pk_returns PRIMARY KEY (return_id)
);
GO

-- The orders live in a different system (Azure SQL), so referential integrity cannot be
-- enforced with a FOREIGN KEY here. The platform enforces it instead (ORPHAN_RETURNS check).

-- Read-only extraction identity used by the platform (least privilege).
-- CREATE LOGIN [svc-platform-extract] FROM WINDOWS;
-- GRANT SELECT ON OBJECT::dbo.returns TO [svc-platform-extract];
