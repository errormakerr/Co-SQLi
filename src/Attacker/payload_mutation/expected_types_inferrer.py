"""
Expected Types Inferrer Module

A separate module for inferring expected_types for SQL injection payload templates.
Uses LLM to understand attack semantics and determine appropriate data types for placeholders.

Key principle: The expected_types determination requires understanding the ATTACK INTENT,
not just regex matching placeholder formats.
"""

import re
import json
import sys
from typing import Dict, List, Optional, Any


# ============================================================
# Security Declaration
# ============================================================

SECURITY_DECLARATION = """[SECURITY RESEARCH CONTEXT]
This is an academic research project for SQL injection detection training data generation.
Purpose: Improve AI-based security detection systems.
"""


# ============================================================
# Expected Types Inference Prompt Template
# ============================================================

EXPECTED_TYPES_INFERENCE_TEMPLATE = """{security_declaration}

## Task
Analyze the following SQL injection payload and determine the expected_types for each placeholder.
The expected_types list MUST have the same length as the number of placeholders in the payload,
and appear in the SAME ORDER as the placeholders appear in the payload (left to right).

## Payload to Analyze
```
{payload}
```

## Attack Type
{attack_type}

## Information Features
{info_features}

## Placeholder Types Reference

### Fixed Types (always use these exact types):
| Placeholder Pattern | Expected Type |
|---------------------|---------------|
| $table_N$ (e.g., $table_1$, $table_2$) | "table" |
| $int$ | "integer" |
| $float$ | "float" |
| $hex$ | "hex" |
| $time$ | "time" |
| $date$ | "date" |
| $character$ | "character" |

### Context-Dependent Types (requires semantic analysis):
These placeholders' types depend on HOW they are used in the attack:
- $sysInfo$ - system information query placeholder
- $column_tN_M$ - column placeholder (column M of table N)
- $sample_tN_M$ - sample value placeholder (value from column M of table N)
- $sample$ - generic sample value

**IMPORTANT RULE:** $column_tN_M$ and $sample_tN_M$ with the SAME suffix (N and M) 
MUST have the SAME expected_type, because they represent the same column.

## Type Selection Rules for Context-Dependent Placeholders

### For Error-Based Attacks:
The goal is to TRIGGER DATABASE ERRORS that reveal information.

**Type Conversion Attacks (CAST, CONVERT):**
- When forcing type conversion with CAST(X AS UNSIGNED/DECIMAL/SIGNED)
- X should be "string" type (non-numeric) to cause conversion error
- Example: `CAST(($sysInfo$) AS UNSIGNED)` → $sysInfo$ should be "string"

**Implicit Conversion Attacks (comparing with numbers):**
- When comparing placeholder with numeric values using =, >, <, etc.
- The placeholder should be "string" type to cause implicit conversion error
- Example: `($sysInfo$)=$int$` → $sysInfo$ should be "string"
- Example: `($sysInfo$)>$int$` → $sysInfo$ should be "string"

**Math Function Attacks (SQRT, LOG, MOD):**
- Math functions expect numbers, passing string causes error
- The placeholder should be "string" type
- Example: `SQRT($sysInfo$)` → $sysInfo$ should be "string"

**XML Function Attacks (extractvalue, updatexml):**
- Used to extract data through error messages
- The inner query content should be "integer" type
- Example: `extractvalue(1, concat($hex$, ($sysInfo$), $hex$))` → $sysInfo$ should be "integer"
- Example: `updatexml(1, concat($hex$, ($sysInfo$), $hex$), 1)` → $sysInfo$ should be "integer"

**GTID Function Attacks (GTID_SUBSET, GTID_SUBTRACT):**
- These functions expect GTID-set strings; passing non-GTID input causes error
- The placeholder should be "integer" type (use a numeric system query to trigger GTID parse error)
- Example: `GTID_SUBSET(($sysInfo$), $character$)=1` → $sysInfo$ should be "integer"
- Example: `GTID_SUBTRACT(($sysInfo$), $character$)=1` → $sysInfo$ should be "integer"

**Date/Time Function Attacks (TO_DAYS, DATE, TIME, YEAR, MONTH, DAY):**
- Passing an integer/numeric value to date functions can cause errors
- The placeholder should be "integer" type
- Example: `TO_DAYS($sysInfo$)=$int$` → $sysInfo$ should be "integer"
- Example: `DATE($sysInfo$)=$date$` → $sysInfo$ should be "string" (date-formatted string)
- Exception: `TIME($sysInfo$)` / `DATE($sysInfo$)` where sysInfo is compared to a date literal → "string"

### For Tautologies Attacks:
The goal is to create ALWAYS-TRUE conditions.

**Numeric Comparisons:**
- When placeholder is compared with integer literals (>, <, =, BETWEEN)
- Use "integer" type for $sysInfo$ (so a numeric system variable is used, e.g., @@port)
- Example: `($sysInfo$)>0` → $sysInfo$ should be "integer"
- Use "number" type for $column_t1_1$ (selects a numeric column from DB)
- Example: `(SELECT $column_t1_1$...)>0` → $column_t1_1$ should be "number"

**String Operations:**
- When using LIKE, REGEXP, string functions
- Use "string" type
- Example: `($sysInfo$) LIKE '%'` → $sysInfo$ should be "string"
- Example: `($sysInfo$) REGEXP '[a-z]'` → $sysInfo$ should be "string"

**Generic True Conditions:**
- IS NOT NULL, EXISTS, COALESCE
- Can use "all" type (any type works)

### For Boolean-Based Inference Attacks:
The goal is to extract data character by character.

**Numeric Comparisons (with SLEEP wrapper or IF):**
- When $sysInfo$ is compared to a number in Boolean/Time-based context
- Use "integer" type for $sysInfo$
- Example: `IF(($sysInfo$)>$int$,1,0)=1` → $sysInfo$ should be "integer"
- Example: `SLEEP($int$) WHERE ($sysInfo$)>0` → $sysInfo$ should be "integer"

**Character Extraction (SUBSTR, LEFT, RIGHT, MID):**
- These functions work on strings
- Target placeholder should be "string" type
- Example: `SUBSTR($sysInfo$,1,1)='a'` → $sysInfo$ should be "string"
- Example: `LEFT($column_t1_1$,1)='x'` → $column_t1_1$ should be "string"

**Length Checks:**
- LENGTH() works on strings
- Use "string" type
- Example: `LENGTH($sysInfo$)>5` → $sysInfo$ should be "string"

**ASCII Conversion:**
- ASCII(SUBSTR(...)) pattern
- Target should be "string"

### For Time-Based Inference Attacks:
Same as Boolean-Based (character extraction), typically use "string" for target data.
For numeric comparisons inside SLEEP/BENCHMARK conditions, use "integer" for $sysInfo$.

### For Union Query Attacks:
- Usually flexible, use "all" for columns being selected
- Example: `UNION SELECT $column_t1_1$ FROM $table_1$` → $column_t1_1$ can be "all"

### For Piggy-Backed Query Attacks:
- Usually flexible, use "all" or specific types based on operation
- For UPDATE SET column=value, the column type determines value type

## Available Type Values
**IMPORTANT: For $sysInfo$ placeholders, use ONLY "string", "integer", or "all".**
**For $column_tN_M$ and $sample_tN_M$ placeholders, use "string", "number", or "all".**
**Never use "number" for $sysInfo$ — use "integer" instead when a numeric system variable is needed.**

- "table" - ONLY for $table_N$ placeholders (table name)
- "string" - for string/text data queries or string-type columns
- "number" - for numeric columns in DB (use for $column_tN_M$/$sample_tN_M$ only)
- "integer" - for $int$ literals AND for $sysInfo$ that should return a numeric value
- "float" - for $float$ literals
- "hex" - for $hex$ literals
- "time" - for $time$ literals
- "date" - for $date$ literals
- "character" - for $character$ literals (single char)
- "all" - when any type is acceptable

## Output Format
Output ONLY a JSON array of types, in the same order as placeholders appear in the payload.
No explanation, no additional text.

Example output for payload with 5 placeholders:
["string", "table", "all", "all", "integer"]

## Your Analysis
Analyze the payload and output the expected_types array:
"""


class ExpectedTypesInferrer:
    """
    Infers expected_types for SQL injection payload templates.
    
    Uses LLM to understand attack semantics and determine appropriate data types.
    Provides fallback heuristic rules when LLM is unavailable.
    """
    
    def __init__(self, llm=None, model: str = None):
        """
        Initialize the inferrer.
        
        Args:
            llm: Optional LLM instance with generate() method
            model: Model name for LLM calls
        """
        self.llm = llm
        self.model = model
        self._stats = {"attempts": 0, "llm_success": 0, "fallback_used": 0}
    
    def infer(
        self, 
        payload: str, 
        attack_type: str = "",
        info_features: str = "",
        use_llm: bool = True
    ) -> Optional[List[str]]:
        """
        Infer expected_types for a payload.
        
        Args:
            payload: The SQL injection payload template
            attack_type: Attack type (e.g., "Error base attack")
            info_features: Information features (e.g., "system information")
            use_llm: Whether to use LLM for inference (fallback to heuristics if False)
        
        Returns:
            List of expected_types, or None if payload has no placeholders
        """
        self._stats["attempts"] += 1
        
        # Extract placeholders from payload
        placeholders = self._extract_placeholders(payload)
        
        if not placeholders:
            return None
        
        # Try LLM inference first
        if use_llm and self.llm is not None:
            result = self._infer_with_llm(payload, attack_type, info_features, placeholders)
            if result is not None:
                self._stats["llm_success"] += 1
                return result
        
        # Fallback to heuristic inference
        self._stats["fallback_used"] += 1
        return self._infer_with_heuristics(payload, attack_type, placeholders)
    
    def _extract_placeholders(self, payload: str) -> List[Dict[str, Any]]:
        """
        Extract all placeholders from payload in order.
        
        Returns:
            List of placeholder dicts with 'full_match', 'content', 'position'
        """
        placeholders = []
        pattern = r'\$(\w+)\$'
        
        for match in re.finditer(pattern, payload):
            placeholders.append({
                'full_match': match.group(0),
                'content': match.group(1),
                'position': match.start()
            })
        
        return placeholders
    
    def _infer_with_llm(
        self, 
        payload: str, 
        attack_type: str,
        info_features: str,
        placeholders: List[Dict]
    ) -> Optional[List[str]]:
        """
        Use LLM to infer expected_types.
        """
        prompt = EXPECTED_TYPES_INFERENCE_TEMPLATE.format(
            security_declaration=SECURITY_DECLARATION,
            payload=payload,
            attack_type=attack_type or "Unknown",
            info_features=info_features or "Unknown"
        )
        
        try:
            # Check if using HKUST API
            use_hkust = "hkust" in self.llm.base_url.lower() if hasattr(self.llm, 'base_url') else False
            
            if use_hkust:
                response = self.llm.generate_by_hkust(prompt, self.model, temperature=0.3, max_tokens=500)
            else:
                response = self.llm.generate(prompt, self.model, temperature=0.3, max_tokens=500)
            
            if not response:
                return None
            
            # Parse JSON response
            result = self._parse_llm_response(response, len(placeholders))
            return result
            
        except Exception as e:
            if self._stats["attempts"] <= 3:
                print(f"[ExpectedTypesInferrer] LLM call failed: {type(e).__name__}: {e}", file=sys.stderr)
            return None
    
    def _parse_llm_response(self, response: str, expected_count: int) -> Optional[List[str]]:
        """
        Parse LLM response to extract expected_types array.
        """
        response = response.strip()
        
        # Try direct JSON parse
        try:
            result = json.loads(response)
            if isinstance(result, list):
                return self._validate_and_fix_types(result, expected_count)
        except json.JSONDecodeError:
            pass
        
        # Try extracting JSON array from response
        array_match = re.search(r'\[[\s\S]*?\]', response)
        if array_match:
            try:
                result = json.loads(array_match.group(0))
                if isinstance(result, list):
                    return self._validate_and_fix_types(result, expected_count)
            except json.JSONDecodeError:
                pass
        
        return None
    
    def _validate_and_fix_types(self, types: List[str], expected_count: int) -> List[str]:
        """
        Validate and fix the types list.
        """
        valid_types = {
            "table", "string", "number", "integer", "float", 
            "hex", "time", "date", "character", "all"
        }
        
        # Fix invalid types
        result = []
        for t in types:
            if isinstance(t, str) and t.lower() in valid_types:
                result.append(t.lower())
            else:
                result.append("all")
        
        # Adjust length
        if len(result) < expected_count:
            result.extend(["all"] * (expected_count - len(result)))
        elif len(result) > expected_count:
            result = result[:expected_count]
        
        return result
    
    def _infer_with_heuristics(
        self, 
        payload: str, 
        attack_type: str,
        placeholders: List[Dict]
    ) -> List[str]:
        """
        Fallback heuristic inference when LLM is unavailable.
        
        Uses pattern matching and attack type to infer types.
        """
        expected_types = []
        attack_type_lower = attack_type.lower() if attack_type else ""
        
        # Analyze payload context for each placeholder
        for ph in placeholders:
            content = ph['content']
            position = ph['position']
            
            # Fixed types
            if re.match(r'table(_\d+)?$', content):
                expected_types.append('table')
            elif content == 'int':
                expected_types.append('integer')
            elif content == 'float':
                expected_types.append('float')
            elif content == 'hex':
                expected_types.append('hex')
            elif content == 'time':
                expected_types.append('time')
            elif content == 'date':
                expected_types.append('date')
            elif content == 'character':
                expected_types.append('character')
            # Context-dependent types
            elif content == 'sysInfo' or re.match(r'(column|sample)_t\d+_\d+$', content) or content == 'sample':
                inferred_type = self._infer_context_type(payload, ph, attack_type_lower)
                expected_types.append(inferred_type)
            else:
                expected_types.append('all')
        
        return expected_types
    
    def _infer_context_type(
        self, 
        payload: str, 
        placeholder: Dict,
        attack_type_lower: str
    ) -> str:
        """
        Infer type for context-dependent placeholders based on surrounding context.
        """
        ph_pattern = re.escape(placeholder['full_match'])
        
        # ──────────────────────────────────────────────────────────
        # Cross-attack-type common patterns: check unambiguous contexts
        # before branching into attack-specific logic.
        # ──────────────────────────────────────────────────────────

        # XML functions (extractvalue / updatexml) content argument → integer
        # (Checked first because XML injection patterns are very distinctive.)
        if re.search(r'(extractvalue|updatexml)\s*\(', payload, re.IGNORECASE):
            # Placeholder is inside concat() → acts as XML path content
            if re.search(rf'concat\s*\([^)]*{ph_pattern}', payload, re.IGNORECASE):
                return 'integer'

        # GTID functions (GTID_SUBSET / GTID_SUBTRACT) first argument → integer
        if re.search(rf'GTID_(SUBSET|SUBTRACT)\s*\(\s*\(?{ph_pattern}', payload, re.IGNORECASE):
            return 'integer'

        # Character-extraction functions (SUBSTR / LEFT / RIGHT / MID) first argument → string
        char_funcs = r'(SUBSTR|SUBSTRING|LEFT|RIGHT|MID)'
        if re.search(rf'{char_funcs}\s*\(\s*\(?{ph_pattern}', payload, re.IGNORECASE):
            return 'string'

        # ASCII(SUBSTR(...)) pattern → string
        if re.search(rf'ASCII\s*\(\s*(SUBSTR|SUBSTRING|LEFT|RIGHT|MID)?\s*\(?{ph_pattern}',
                     payload, re.IGNORECASE):
            return 'string'

        # LENGTH() argument → string
        if re.search(rf'LENGTH\s*\(\s*{ph_pattern}', payload, re.IGNORECASE):
            return 'string'

        # Left-hand side of LIKE / REGEXP → string
        if re.search(rf'{ph_pattern}\s*\)?\s*LIKE', payload, re.IGNORECASE):
            return 'string'
        if re.search(rf'{ph_pattern}\s*\)?\s*REGEXP', payload, re.IGNORECASE):
            return 'string'

        # ──────────────────────────────────────────────────────────
        # Error-based attack patterns
        # ──────────────────────────────────────────────────────────
        if 'error' in attack_type_lower:
            # CAST/CONVERT: passing a string into a numeric cast triggers a conversion error
            if re.search(rf'CAST\s*\(\s*\(?{ph_pattern}', payload, re.IGNORECASE):
                return 'string'
            if re.search(rf'CONVERT\s*\(\s*\(?{ph_pattern}', payload, re.IGNORECASE):
                return 'string'
            
            # Math functions: passing a non-numeric argument triggers an error
            math_funcs = r'(SQRT|LOG|LOG2|LOG10|LN|MOD|EXP|POW|POWER)'
            if re.search(rf'{math_funcs}\s*\(\s*\(?{ph_pattern}', payload, re.IGNORECASE):
                return 'string'
            
            # Comparison with a number: implicit conversion from string triggers an error
            if re.search(rf'{ph_pattern}\s*\)?\s*[><=!]+\s*\$int\$', payload):
                return 'string'
            if re.search(rf'{ph_pattern}\s*\)?\s*[><=!]+\s*\d+', payload):
                return 'string'
            
            # GTID functions (fallback; primary check is in the common section above)
            if re.search(r'GTID_(SUBSET|SUBTRACT)', payload, re.IGNORECASE):
                return 'integer'

            # Date/time functions: passing an integer to a date function triggers a type error
            date_funcs = r'(TO_DAYS|FROM_DAYS|YEAR|MONTH|DAY|HOUR|MINUTE|SECOND|WEEKDAY|DAYOFWEEK)'
            if re.search(rf'{date_funcs}\s*\(\s*\(?{ph_pattern}', payload, re.IGNORECASE):
                return 'integer'
            # DATE() / TIME() with a string argument triggers a format error
            if re.search(rf'(DATE|TIME)\s*\(\s*\(?{ph_pattern}', payload, re.IGNORECASE):
                return 'string'

            # XML functions (fallback; primary check is in the common section above)
            if re.search(r'(extractvalue|updatexml)', payload, re.IGNORECASE):
                return 'integer'
            
            return 'string'  # Default for error-based attacks
        
        # ──────────────────────────────────────────────────────────
        # Tautologies attack patterns
        # ──────────────────────────────────────────────────────────
        if 'tautolog' in attack_type_lower:
            # Numeric comparisons: use "integer" for $sysInfo$, "number" for DB columns
            is_sysinfo = 'sysInfo' in placeholder.get('content', placeholder['full_match'])
            if re.search(rf'{ph_pattern}\s*\)?\s*[><=]+\s*\d+', payload):
                return 'integer' if is_sysinfo else 'number'
            if re.search(rf'{ph_pattern}\s*\)?\s*[><=]+\s*\$int\$', payload):
                return 'integer' if is_sysinfo else 'number'
            if re.search(rf'{ph_pattern}\s*\)?\s*BETWEEN', payload, re.IGNORECASE):
                return 'integer' if is_sysinfo else 'number'
            
            return 'all'
        
        # ──────────────────────────────────────────────────────────
        # Boolean / Time inference attack patterns
        # ──────────────────────────────────────────────────────────
        if 'inference' in attack_type_lower or 'boolean' in attack_type_lower or 'time' in attack_type_lower:
            # Numeric comparison inside IF/WHERE → integer (applicable to $sysInfo$)
            is_sysinfo = 'sysInfo' in placeholder.get('content', placeholder['full_match'])
            if is_sysinfo:
                if re.search(rf'{ph_pattern}\s*\)?\s*[><=!]+\s*(\d+|\$int\$)', payload):
                    return 'integer'
                if re.search(rf'IF\s*\(\s*\(?{ph_pattern}', payload, re.IGNORECASE):
                    return 'integer'
            
            return 'string'  # Default for inference attacks
        
        # Union query / Piggy-backed: usually flexible, any type is acceptable
        if 'union' in attack_type_lower or 'piggy' in attack_type_lower:
            return 'all'
        
        # Default fallback
        return 'all'
    
    def get_stats(self) -> Dict:
        """Get inference statistics."""
        return {
            "total_attempts": self._stats["attempts"],
            "llm_success": self._stats["llm_success"],
            "fallback_used": self._stats["fallback_used"],
            "llm_success_rate": self._stats["llm_success"] / self._stats["attempts"] if self._stats["attempts"] > 0 else 0
        }
    
    def reset_stats(self):
        """Reset statistics."""
        self._stats = {"attempts": 0, "llm_success": 0, "fallback_used": 0}


# ============================================================
# Standalone inference function (for simple use cases)
# ============================================================

def infer_expected_types(
    payload: str,
    attack_type: str = "",
    info_features: str = ""
) -> Optional[List[str]]:
    """
    Standalone function to infer expected_types using heuristics only.
    
    Use this when LLM is not available.
    """
    inferrer = ExpectedTypesInferrer()
    return inferrer.infer(payload, attack_type, info_features, use_llm=False)
