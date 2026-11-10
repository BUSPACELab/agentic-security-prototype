
"""Validate LLM-generated SQL and restrict it to the current user."""

from dataclasses import dataclass
from sqlglot import exp, parse
from sqlglot.errors import ParseError
from .actions import *


class SQLValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SQLOperation:
    action: str
    table: str
    safe_query: str


READ_COLUMNS = {
    "auth_user": {"id", "username", "email", "first_name", "last_name"},
    "files_uploadedfile": {"id", "title", "file", "created_at"},
}

UPDATE_COLUMNS = {"username", "email", "first_name", "last_name"}

ALLOWED = (
    exp.Select, exp.Update, exp.From, exp.Table, exp.Column,
    exp.Identifier, exp.Literal, exp.Where, exp.EQ, exp.NEQ,
    exp.And, exp.Or, exp.Not, exp.Paren, exp.GT, exp.GTE,
    exp.LT, exp.LTE, exp.Like, exp.Between, exp.In, exp.Is,
    exp.Null, exp.Order, exp.Ordered, exp.Limit,
    exp.Group, exp.Having,
    exp.Count, exp.Date, exp.Star, exp.Alias,
)


def inspect_sql(query: str, context: str, user_id: str) -> SQLOperation:
    """Return the authorized action and user-scoped SQL."""

    # Ensure the query is within reasonable length limits and is a string
    if not isinstance(query, str) or len(query) > 10000:
        raise SQLValidationError("Invalid SQL query.")

    try:
        # parse the query and the user_id
        statements = parse(query, read="sqlite")
        uid = int(user_id)
    except (ParseError, ValueError, TypeError) as error:
        raise SQLValidationError("Invalid SQL or user.") from error

    # validate the query and user
    if uid <= 0 or len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Update)):
        raise SQLValidationError("Unsupported SQL statement.")

    statement = statements[0]
    tables = list(statement.find_all(exp.Table))

    # validate the table and ensure only one table is used, and that it is not aliased or qualified with a database/catalog
    if len(tables) != 1 or tables[0].db or tables[0].catalog or tables[0].alias:
        raise SQLValidationError("Only one table is allowed.")

    table = tables[0]
    name = table.name.lower()
    updating = isinstance(statement, exp.Update)

    # validate the action and the table based on the context and whether it is an update or read operation
    if context == FILE_CONTEXT and name == "files_uploadedfile" and not updating:
        action, owner_column = FILE_METADATA_READ, "owner_id"
    elif context == PROFILE_CONTEXT and name == "auth_user":
        action, owner_column = (ACCOUNT_UPDATE if updating else ACCOUNT_READ), "id"
    else:
        raise SQLValidationError("Operation not allowed in this context.")

    # define the allowed arguments based on whether it is an update or read operation
    allowed_args = {"this", "expressions", "where"} if updating else {"expressions", "from_", "where", "order", "limit", "group", "having"}

    if any(value is not None for key, value in statement.args.items() if key not in allowed_args):
        raise SQLValidationError("Unsupported SQL clause.")

    source = statement.this if updating else statement.args.get("from_")
    if not updating:
        source = source.this if source and not source.expressions else None

    if source is not table or any(not isinstance(node, ALLOWED) for node in statement.walk()):
        raise SQLValidationError("Unsupported SQL structure.")

    if updating:
        if not statement.expressions or any(
            not isinstance(item, exp.EQ)
            or not isinstance(item.this, exp.Column)
            or item.this.table or item.this.name.lower() not in UPDATE_COLUMNS
            or not isinstance(item.expression, exp.Literal)
            or not item.expression.is_string
            for item in statement.expressions
        ):
            raise SQLValidationError("Invalid profile update.")

    elif len(statement.expressions) == 1 and isinstance(statement.expressions[0], exp.Star):
        statement.set("expressions", [exp.column(column) for column in sorted(READ_COLUMNS[name])])

    for column in statement.find_all(exp.Column):
        if column.name.lower() not in READ_COLUMNS[name] or column.table.lower() not in ("", name):
            raise SQLValidationError("Column not allowed.")

    if any(not isinstance(star.parent, exp.Count) for star in statement.find_all(exp.Star)):
        raise SQLValidationError("Wildcard not allowed.")

    safe_query = statement.where(f"{owner_column} = {uid}", append=True).sql(dialect="sqlite")
    return SQLOperation(action, name, safe_query)
