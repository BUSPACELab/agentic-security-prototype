
"""Validate SQL before authorization."""

from sqlglot import exp, parse
from sqlglot.errors import ParseError


# SQL expressions supported by the system
ALLOWED_NODES = frozenset((
    exp.Select, exp.Update, exp.Table, exp.TableAlias,
    exp.Identifier, exp.Column, exp.Alias,
    exp.From, exp.Where, exp.Order, exp.Ordered,
    exp.Limit, exp.Offset, exp.Distinct, exp.Group,
    exp.Having, exp.Star,
    exp.Literal, exp.Null, exp.Paren,
    exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
    exp.And, exp.Or, exp.Not, exp.Is, exp.In,
    exp.Like, exp.Between,
    exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg,
    exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max,
))


def validate_sql(query: str, dialect: str = "sqlite"):
    """Validate the SQL structure before authorization."""

    # Reject empty or too long SQL queries
    if not isinstance(query, str) or not query.strip() or len(query) > 10000:
        raise ValueError("Invalid SQL query.")

    # Parse the query using the configured SQL dialect
    try:
        statements = parse(query, read=dialect)
    except ParseError as error:
        raise ValueError("Invalid SQL query.") from error

    # Only allow one SELECT or UPDATE statement
    if len(statements) != 1 or type(statements[0]) not in (exp.Select, exp.Update):
        raise ValueError("Only SELECT and UPDATE are supported.")


    statement = statements[0]
    reading = isinstance(statement, exp.Select)
    tables = list(statement.find_all(exp.Table))

    # Only use one table from the current database
    if len(tables) != 1 or tables[0].db or tables[0].catalog:
        raise ValueError("Only one table is supported.")

    # Only allow supported SQL clauses
    allowed_args = ({"expressions", "from_", "where", "order", "limit", "offset", "distinct", "group", "having"} if reading else {"this", "expressions", "where"})

    # Reject unsupported arguments
    if any(value is not None for key, value in statement.args.items() if key not in allowed_args):
        raise ValueError("Unsupported SQL clause.")

    # Make sure the query reads or updates the expected table 
    if reading:
        source = statement.args.get("from_")
        if source is None or source.this is not tables[0] or source.expressions:
            raise ValueError("Unsupported SQL source.")
    elif statement.this is not tables[0]:
        raise ValueError("Unsupported update target.")


    # Reject unsupported expression types or nested queries
    if any(type(node) not in ALLOWED_NODES for node in statement.walk()):
        raise ValueError("Unsupported SQL expression.")

    # Only allow simple values when updating columns
    if not reading and (not statement.expressions or any(
        not isinstance(item, exp.EQ) or not isinstance(item.this, exp.Column)
        or item.this.table or item.this.db or item.this.catalog
        or not isinstance(item.expression, (exp.Literal, exp.Null))
        for item in statement.expressions
    )):
        raise ValueError("Unsupported UPDATE assignment.")

    
    # Reject references outside the selected table
    table = tables[0].alias_or_name.lower()

    if any(column.db or column.catalog or (column.table and column.table.lower() != table) for column in statement.find_all(exp.Column)):
        raise ValueError("Unsupported column reference.")


    return statement
