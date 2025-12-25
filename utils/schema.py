def get_schema(db, schemas):
    schema = None
    for item in schemas:
        if item['database_name'] != db:
            continue
        else:
            schema = item
    return schema