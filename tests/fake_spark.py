"""A tiny DuckDB-backed stand-in for the parts of PySpark the Fabric notebook uses.

It lets CI execute the real notebook source end to end without Java or Spark. It validates the
notebook's control flow, contract handling and SQL (which is written in the DuckDB/Spark common
subset). It does not validate Spark-specific behaviour such as Delta writes or type coercion.
"""

from __future__ import annotations

import itertools
import re
import sys
import types
from datetime import UTC, datetime

import duckdb

_counter = itertools.count()


def split_ddl(ddl: str) -> list[tuple[str, str]]:
    parts, depth, current = [], 0, ""
    for char in ddl:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [tuple(p.strip().split(" ", 1)) for p in parts if p.strip()]


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def asDict(self):
        return dict(self)


class Lit:
    def __init__(self, value):
        self.value = value


def install_pyspark_module() -> None:
    functions = types.ModuleType("pyspark.sql.functions")
    functions.lit = Lit
    sql = types.ModuleType("pyspark.sql")
    sql.functions = functions
    pyspark = types.ModuleType("pyspark")
    pyspark.sql = sql
    sys.modules.update({"pyspark": pyspark, "pyspark.sql": sql, "pyspark.sql.functions": functions})


def _literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


class DataFrame:
    def __init__(self, spark: FakeSpark, relation: duckdb.DuckDBPyRelation):
        self.spark = spark
        self.relation = relation

    @property
    def columns(self) -> list[str]:
        return list(self.relation.columns)

    @property
    def write(self) -> Writer:
        return Writer(self)

    def withColumn(self, name, value):
        return DataFrame(self.spark, self.relation.project(f"*, {_literal(value.value)} AS {name}"))

    def select(self, *names):
        return DataFrame(self.spark, self.relation.project(", ".join(names)))

    def limit(self, n):
        return DataFrame(self.spark, self.relation.limit(n))

    def count(self) -> int:
        return len(self.relation.fetchall())

    def collect(self) -> list[Row]:
        return [Row(zip(self.columns, row, strict=True)) for row in self.relation.fetchall()]

    def first(self):
        rows = DataFrame(self.spark, self.relation.limit(1)).collect()
        return rows[0] if rows else None


class Writer:
    def __init__(self, df: DataFrame):
        self.df = df
        self._mode = "error"

    def mode(self, mode):
        self._mode = mode
        return self

    def option(self, *_):
        return self

    def format(self, _):
        return self

    def saveAsTable(self, name):
        con = self.df.spark.con
        temp = f"__save_{next(_counter)}"
        self.df.relation.create(temp)
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()[0]
        if self._mode == "append" and exists:
            con.execute(f"INSERT INTO {name} SELECT * FROM {temp}")
        else:
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {temp}")
        con.execute(f"DROP TABLE {temp}")


class Reader:
    def __init__(self, spark: FakeSpark):
        self.spark = spark
        self._schema = None

    def option(self, *_):
        return self

    def schema(self, ddl):
        self._schema = split_ddl(ddl)
        return self

    def csv(self, path):
        path = str(path).replace("'", "''")
        if self._schema:
            columns = ", ".join(f"'{n}': '{t}'" for n, t in self._schema)
            sql = f"SELECT * FROM read_csv('{path}', header = true, columns = {{{columns}}})"
        else:
            sql = f"SELECT * FROM read_csv('{path}', header = true, all_varchar = true)"
        temp = f"__csv_{next(_counter)}"
        self.spark.con.execute(f"CREATE TABLE {temp} AS {sql}")
        return DataFrame(self.spark, self.spark.con.table(temp))


class Conf:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value


class FakeSpark:
    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con
        self.conf = Conf()

    @property
    def read(self) -> Reader:
        return Reader(self)

    def sql(self, sql: str):
        if re.match(r"\s*CREATE\s", sql, re.IGNORECASE):
            self.con.execute(re.sub(r"\s+USING\s+DELTA", "", sql, flags=re.IGNORECASE))
            return None
        return DataFrame(self.spark_self(), self.con.sql(sql))

    def spark_self(self):
        return self

    def table(self, name):
        return DataFrame(self, self.con.table(name))

    def createDataFrame(self, rows, ddl):
        columns = split_ddl(ddl)
        temp = f"__rows_{next(_counter)}"
        self.con.execute(f"CREATE TABLE {temp} ({', '.join(f'{n} {t}' for n, t in columns)})")
        placeholders = ", ".join("?" for _ in columns)
        for row in rows:
            values = [
                v.astimezone(UTC).replace(tzinfo=None)
                if isinstance(v, datetime) and v.tzinfo
                else v
                for v in row
            ]
            self.con.execute(f"INSERT INTO {temp} VALUES ({placeholders})", values)
        return DataFrame(self, self.con.table(temp))
