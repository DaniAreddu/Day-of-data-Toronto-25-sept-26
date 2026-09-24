-- Source contract: operational orders (Azure SQL Database representation).
--
-- Synthetic, production-inspired scenario. It does not represent a real customer deployment.
-- No Azure SQL database is required: sample-data/azure-sql/orders.csv is a synthetic
-- change-data-capture extract that conforms to this contract.
--
-- Contract: contracts/orders.contract.yml (version 1.0.0)
-- Grain:    one row per order change event (the extract may contain several rows per order_id)
-- All timestamps are UTC.

CREATE SCHEMA sales;
GO

CREATE TABLE sales.orders
(
    order_id            varchar(20)    NOT NULL,  -- business key, e.g. SO-202608-00001
    event_id            varchar(24)    NOT NULL,  -- CDC event identifier
    event_version       int            NOT NULL,  -- increases when the order is amended
    order_timestamp_utc datetime2(0)   NOT NULL,  -- transaction time (UTC)
    region_code         char(2)        NOT NULL,  -- ON, QC, BC, AB
    category_code       char(3)        NOT NULL,  -- DEV, ACC, SVC
    currency_code       char(3)        NOT NULL,  -- accepted: CAD, USD
    gross_amount        decimal(12, 2) NOT NULL,  -- in currency_code, before returns
    customer_segment    varchar(20)    NOT NULL,  -- Consumer, SMB, Enterprise, Internal Test
    source_updated_at   datetime2(0)   NOT NULL,  -- last change in the source row (UTC)
    ingested_at         datetime2(0)   NOT NULL,  -- when the extract landed (UTC)
    CONSTRAINT pk_orders_event PRIMARY KEY (order_id, event_id),
    CONSTRAINT ck_orders_currency CHECK (currency_code IN ('CAD', 'USD'))
);
GO

-- Read-only extraction identity used by the platform (least privilege).
-- CREATE USER [svc-platform-extract] FROM EXTERNAL PROVIDER;
-- GRANT SELECT ON OBJECT::sales.orders TO [svc-platform-extract];
