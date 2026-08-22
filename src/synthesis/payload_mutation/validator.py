"""
Mutation Result Validator

Validates mutated payloads against requirements:
1. Single line output
2. Placeholder preservation (no missing, no illegal introduction)
3. Reference-scope consistency (LOR must remain placeholder-free)
4. Technique consistency
5. Basic SQL syntax
"""

import re
from dataclasses import dataclass
from typing import Dict, List

from .type_identifier import Technique, identify


@dataclass
class ValidationResult:
    """Validation result with standardized reason keywords."""
    is_valid: bool
    reason: str = ""
    suggestions: List[str] = None
    
    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


class PayloadValidator:
    """
    Payload validator with multiple checks.
    
    Reason keywords are standardized for memory module matching:
    - "empty": Empty output
    - "multiline": Multiple lines
    - "placeholder": Missing or illegal placeholders
    - "syntax": SQL syntax error
    - "technique": Technique mismatch
    """
    
    def validate(self, original: Dict, mutated_payload: str) -> ValidationResult:
        """
        Validate mutation result.
        
        Args:
            original: Original payload template dict
            mutated_payload: Mutated payload string
        
        Returns:
            ValidationResult object
        """
        # Step 1: Basic cleaning (remove LLM formatting artifacts, but NOT take first line yet)
        mutated_payload = self._pre_clean(mutated_payload)
        
        # Step 2: Run format checks first (before taking first line)
        format_checks = [
            self._check_not_empty,
            self._check_single_line,  # Now runs on the uncropped output
        ]
        for check in format_checks:
            result = check(original, mutated_payload)
            if not result.is_valid:
                return result
        
        # Step 3: Extract the single line (safe to do now that single-line is confirmed)
        mutated_payload = self._extract_line(mutated_payload)
        
        # Step 4: Run content checks on the cleaned single-line payload
        content_checks = [
            self._check_placeholders,
            self._check_reference_scope_consistency,
            self._check_comment_free_core,
            self._check_parenthesis_balance,
            self._check_technique,
        ]
        for check in content_checks:
            result = check(original, mutated_payload)
            if not result.is_valid:
                return result
        
        return ValidationResult(is_valid=True)
    
    def clean(self, mutated_payload: str) -> str:
        """
        Public method: clean and extract the single-line payload from LLM output.
        Used externally to get the final cleaned payload string.
        """
        cleaned = self._pre_clean(mutated_payload)
        return self._extract_line(cleaned)
    
    def _pre_clean(self, output: str) -> str:
        """
        Remove LLM formatting artifacts WITHOUT taking first line.
        Preserves multi-line structure so _check_single_line can detect violations.
        """
        output = output.strip()
        
        # Remove common English prefixes
        prefixes = ["Payload:", "payload:", "Result:", "Mutated:", "Output:"]
        for prefix in prefixes:
            if output.startswith(prefix):
                output = output[len(prefix):].strip()
                break
        
        # Remove code block markers (```sql ... ``` or ``` ... ```)
        output = re.sub(r'```\w*\n?', '', output)
        
        return output.strip()
    
    def _extract_line(self, output: str) -> str:
        """
        Extract the single payload line from (already cleaned) output.
        Takes the first non-empty line.
        """
        lines = [line.strip() for line in output.split('\n') if line.strip()]
        if lines:
            return lines[0]
        return output.strip()
    
    def _check_not_empty(self, original: Dict, mutated: str) -> ValidationResult:
        """Check if output is empty."""
        if not mutated or not mutated.strip():
            return ValidationResult(
                is_valid=False,
                reason="empty output",
                suggestions=["LLM did not generate valid output"]
            )
        return ValidationResult(is_valid=True)
    
    def _check_single_line(self, original: Dict, mutated: str) -> ValidationResult:
        """
        Check if output is a single payload line.
        Operates on pre-cleaned but NOT yet line-extracted output.
        """
        lines = [l.strip() for l in mutated.split('\n') if l.strip()]
        if len(lines) > 1:
            return ValidationResult(
                is_valid=False,
                reason="multiline output",
                suggestions=["Should output only one payload, no explanations"]
            )
        return ValidationResult(is_valid=True)
    
    def _check_placeholders(self, original: Dict, mutated: str) -> ValidationResult:
        """
        Check if required placeholders are preserved.
        
        For payloads that originally have placeholders, all core placeholders
        ($table_x$, $column_x$, $sysInfo$) must be kept.
        Exception: specific_database allows structural restructuring as long as
        the placeholder COUNT and TYPE CATEGORY are consistent.
        """
        original_payload = original.get("payload", "")
        reference_scope = original.get("reference_scope", "")
        
        original_ph = set(re.findall(r'\$\w+\$', original_payload))
        mutated_ph = set(re.findall(r'\$\w+\$', mutated))
        
        # No placeholders in original → nothing to check here
        # Reference-scope consistency is checked separately below.
        if not original_ph:
            return ValidationResult(is_valid=True)
        
        # Core placeholders that must be preserved (structural identifiers)
        core_ph = {p for p in original_ph if any(k in p for k in ['table', 'column', 'sysInfo'])}
        missing = core_ph - mutated_ph
        
        if not missing:
            return ValidationResult(is_valid=True)
        
        # For specific_database: allow structural restructuring, but require
        # that at least some DB-structural placeholders remain (not all gone)
        if reference_scope == "tsr":
            mutated_structural = {p for p in mutated_ph if any(k in p for k in ['table', 'column'])}
            if mutated_structural:
                # Still has table/column placeholders — structural change is acceptable
                return ValidationResult(is_valid=True)
            else:
                return ValidationResult(
                    is_valid=False,
                    reason=f"placeholder missing: all structural placeholders removed",
                    suggestions=[f"Must preserve table/column placeholders; missing: {', '.join(missing)}"]
                )
        
        return ValidationResult(
            is_valid=False,
            reason=f"placeholder missing: {missing}",
            suggestions=[f"Must preserve: {', '.join(missing)}"]
        )
    
    def _check_reference_scope_consistency(self, original: Dict, mutated: str) -> ValidationResult:
        """
        Check that the canonical reference_scope has not changed.
        
        - constant:          mutated must have NO $xxx$ placeholders
        - system information: mutated must NOT introduce $table_x$/$column_x$ placeholders
        - specific database:  mutated must NOT introduce $sysInfo$ if original had none
        """
        reference_scope = original.get("reference_scope", "")
        original_payload = original.get("payload", "")
        
        original_ph = set(re.findall(r'\$\w+\$', original_payload))
        mutated_ph = set(re.findall(r'\$\w+\$', mutated))
        
        if reference_scope == "lor":
            # constant payloads must remain placeholder-free
            if mutated_ph:
                return ValidationResult(
                    is_valid=False,
                    reason=f"reference_scope violation: LOR payload gained placeholders {mutated_ph}",
                    suggestions=[
                        "constant payloads must not contain $xxx$ placeholders",
                        "Do not introduce $sysInfo$, $table_x$, or $column_x$ style tokens"
                    ]
                )
        
        elif reference_scope == "scr":
            # system information payloads must not introduce database-specific placeholders
            db_placeholders_in_mutated = {
                p for p in mutated_ph
                if any(k in p for k in ['table', 'column', 'sample'])
                and p not in original_ph
            }
            if db_placeholders_in_mutated:
                return ValidationResult(
                    is_valid=False,
                    reason=f"reference_scope violation: SCR payload gained DB-specific placeholders {db_placeholders_in_mutated}",
                    suggestions=[
                        "system information payloads must only use $sysInfo$ style placeholders",
                        "Do not introduce $table_x$ or $column_x$ placeholders"
                    ]
                )
        
        elif reference_scope == "tsr":
            # specific database payloads should not degrade to pure $sysInfo$ only
            # (covered by _check_placeholders, but add sysInfo-only detection)
            original_has_sys_info = any('sysInfo' in p for p in original_ph)
            mutated_has_sys_info_new = any(
                'sysInfo' in p for p in mutated_ph if p not in original_ph
            )
            mutated_structural = {p for p in mutated_ph if any(k in p for k in ['table', 'column'])}
            if not original_has_sys_info and mutated_has_sys_info_new and not mutated_structural:
                return ValidationResult(
                    is_valid=False,
                    reason="reference_scope violation: TSR payload converted to SCR style",
                    suggestions=[
                        "specific database payloads must retain table/column placeholders",
                        "Do not replace all structural placeholders with $sysInfo$"
                    ]
            )
        
        return ValidationResult(is_valid=True)
    
    def _check_comment_free_core(self, original: Dict, mutated: str) -> ValidationResult:
        """Mutation must not leak comment-state control into a payload core."""
        del original
        if "--" in mutated or "#" in mutated:
            return ValidationResult(
                is_valid=False,
                reason="comment delimiter introduced",
                suggestions=["Payload mutation only returns a comment-free core; use no -- or #"],
            )
        return ValidationResult(is_valid=True)
    
    def _check_parenthesis_balance(self, original: Dict, mutated: str) -> ValidationResult:
        """
        Check if parentheses are balanced (after removing comment suffix).
        
        Note: Single-quote balance is intentionally NOT checked — SQL injection
        payloads are designed to have unbalanced quotes to escape the original query.
        """
        if mutated.count('(') != mutated.count(')'):
            return ValidationResult(
                is_valid=False,
                reason="syntax error: parenthesis unbalanced",
                suggestions=["Check parentheses matching"]
            )
        
        return ValidationResult(is_valid=True)
    
    def _check_technique(self, original: Dict, mutated: str) -> ValidationResult:
        """
        Check if technique is consistent.
        
        Note: This check has limited effectiveness because the type_identifier
        may return UNKNOWN for many valid payloads. It serves as a best-effort
        guard against clear type violations (e.g., SLEEP appearing in an
        Error base attack).
        """
        original_technique = original.get("technique", "")
        
        if not original_technique:
            return ValidationResult(is_valid=True)
        
        # Identify the mutated technique.
        mutated_template = {"payload": mutated}
        mutated_technique, _ = identify(mutated_template)
        
        # Compatible types mapping (these can legitimately overlap)
        compatible = {
            Technique.TAUTOLOGY: [Technique.BOOLEAN_BLIND],
            Technique.BOOLEAN_BLIND: [Technique.TAUTOLOGY],
        }
        
        try:
            expected_technique = Technique(original_technique)
            
            # UNKNOWN means identifier could not determine type — allow it
            if mutated_technique == Technique.UNKNOWN:
                return ValidationResult(is_valid=True)
            
            # Exact match
            if mutated_technique == expected_technique:
                return ValidationResult(is_valid=True)
            
            # Compatible match
            if mutated_technique in compatible.get(expected_technique, []):
                return ValidationResult(is_valid=True)
            
            # Clear mismatch: identified a different known technique.
            return ValidationResult(
                is_valid=False,
                reason=f"technique mismatch: expected {original_technique}, got {mutated_technique.value}",
                suggestions=[
                    f"Mutated payload appears to be {mutated_technique.value}, not {original_technique}",
                    "Keep the same attack category while changing the implementation method"
                ]
            )
                    
        except ValueError:
            # Unknown taxonomy values are rejected elsewhere; preserve this
            # fallback for standalone validator use.
            return ValidationResult(is_valid=True)


def validate_mutation(original: Dict, mutated_payload: str) -> ValidationResult:
    """Convenience function to validate a mutation."""
    return PayloadValidator().validate(original, mutated_payload)
