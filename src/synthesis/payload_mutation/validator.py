"""
Mutation Result Validator

Validates mutated payloads against requirements:
1. Single line output
2. Placeholder preservation (no missing, no illegal introduction)
3. Information feature consistency (constant must remain placeholder-free)
4. Attack type consistency
5. Basic SQL syntax
"""

import re
from dataclasses import dataclass
from typing import Dict, List

from .type_identifier import identify, AttackType


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
    - "info_feature": Information feature category changed
    - "comment": Missing comment terminator
    - "syntax": SQL syntax error
    - "type": Attack type mismatch
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
            self._check_info_feature_consistency,
            self._check_comment_terminator,
            self._check_parenthesis_balance,
            self._check_attack_type,
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
        info_feature = original.get("information_features", "")
        
        original_ph = set(re.findall(r'\$\w+\$', original_payload))
        mutated_ph = set(re.findall(r'\$\w+\$', mutated))
        
        # No placeholders in original → nothing to check here
        # (info_feature consistency handled separately in _check_info_feature_consistency)
        if not original_ph:
            return ValidationResult(is_valid=True)
        
        # Core placeholders that must be preserved (structural identifiers)
        core_ph = {p for p in original_ph if any(k in p for k in ['table', 'column', 'sysInfo'])}
        missing = core_ph - mutated_ph
        
        if not missing:
            return ValidationResult(is_valid=True)
        
        # For specific_database: allow structural restructuring, but require
        # that at least some DB-structural placeholders remain (not all gone)
        if info_feature == "specific database":
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
    
    def _check_info_feature_consistency(self, original: Dict, mutated: str) -> ValidationResult:
        """
        Check that information_features category has not changed.
        
        - constant:          mutated must have NO $xxx$ placeholders
        - system information: mutated must NOT introduce $table_x$/$column_x$ placeholders
        - specific database:  mutated must NOT introduce $sysInfo$ if original had none
        """
        info_feature = original.get("information_features", "")
        original_payload = original.get("payload", "")
        
        original_ph = set(re.findall(r'\$\w+\$', original_payload))
        mutated_ph = set(re.findall(r'\$\w+\$', mutated))
        
        if info_feature == "constant":
            # constant payloads must remain placeholder-free
            if mutated_ph:
                return ValidationResult(
                    is_valid=False,
                    reason=f"info_feature violation: constant payload gained placeholders {mutated_ph}",
                    suggestions=[
                        "constant payloads must not contain $xxx$ placeholders",
                        "Do not introduce $sysInfo$, $table_x$, or $column_x$ style tokens"
                    ]
                )
        
        elif info_feature == "system information":
            # system information payloads must not introduce database-specific placeholders
            db_placeholders_in_mutated = {
                p for p in mutated_ph
                if any(k in p for k in ['table', 'column', 'sample'])
                and p not in original_ph
            }
            if db_placeholders_in_mutated:
                return ValidationResult(
                    is_valid=False,
                    reason=f"info_feature violation: system information payload gained DB-specific placeholders {db_placeholders_in_mutated}",
                    suggestions=[
                        "system information payloads must only use $sysInfo$ style placeholders",
                        "Do not introduce $table_x$ or $column_x$ placeholders"
                    ]
                )
        
        elif info_feature == "specific database":
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
                    reason="info_feature violation: specific database payload converted to system information style",
                    suggestions=[
                        "specific database payloads must retain table/column placeholders",
                        "Do not replace all structural placeholders with $sysInfo$"
                    ]
            )
        
        return ValidationResult(is_valid=True)
    
    def _check_comment_terminator(self, original: Dict, mutated: str) -> ValidationResult:
        """Check if comment terminator is preserved."""
        original_payload = original.get("payload", "")
        
        has_original_comment = bool(re.search(r'(--|#)\s*$', original_payload))
        has_mutated_comment = bool(re.search(r'(--|#)\s*$', mutated))
        
        if has_original_comment and not has_mutated_comment:
            return ValidationResult(
                is_valid=False,
                reason="comment terminator missing",
                suggestions=["Payload should end with -- or #"]
            )
        
        return ValidationResult(is_valid=True)
    
    def _check_parenthesis_balance(self, original: Dict, mutated: str) -> ValidationResult:
        """
        Check if parentheses are balanced (after removing comment suffix).
        
        Note: Single-quote balance is intentionally NOT checked — SQL injection
        payloads are designed to have unbalanced quotes to escape the original query.
        """
        # Remove comment part before checking
        payload = re.sub(r'(--|#).*$', '', mutated)
        
        if payload.count('(') != payload.count(')'):
            return ValidationResult(
                is_valid=False,
                reason="syntax error: parenthesis unbalanced",
                suggestions=["Check parentheses matching"]
            )
        
        return ValidationResult(is_valid=True)
    
    def _check_attack_type(self, original: Dict, mutated: str) -> ValidationResult:
        """
        Check if attack type is consistent.
        
        Note: This check has limited effectiveness because the type_identifier
        may return UNKNOWN for many valid payloads. It serves as a best-effort
        guard against clear type violations (e.g., SLEEP appearing in an
        Error base attack).
        """
        original_type = original.get("type", "")
        
        if not original_type:
            return ValidationResult(is_valid=True)
        
        # Identify mutated type
        mutated_template = {"payload": mutated, "type": None, "information_features": None}
        mutated_type, _ = identify(mutated_template)
        
        # Compatible types mapping (these can legitimately overlap)
        compatible = {
            AttackType.TAUTOLOGIES: [AttackType.BOOLEAN_INFERENCE],
            AttackType.BOOLEAN_INFERENCE: [AttackType.TAUTOLOGIES],
        }
        
        try:
            original_attack_type = AttackType(original_type)
            
            # UNKNOWN means identifier could not determine type — allow it
            if mutated_type == AttackType.UNKNOWN:
                return ValidationResult(is_valid=True)
            
            # Exact match
            if mutated_type == original_attack_type:
                return ValidationResult(is_valid=True)
            
            # Compatible match
            if mutated_type in compatible.get(original_attack_type, []):
                return ValidationResult(is_valid=True)
            
            # Clear mismatch: identified a DIFFERENT known attack type
            return ValidationResult(
                is_valid=False,
                reason=f"type mismatch: expected {original_type}, got {mutated_type.value}",
                suggestions=[
                    f"Mutated payload appears to be {mutated_type.value}, not {original_type}",
                    "Keep the same attack category while changing the implementation method"
                ]
            )
                    
        except ValueError:
            # original_type not a known AttackType enum value — skip check
            return ValidationResult(is_valid=True)


def validate_mutation(original: Dict, mutated_payload: str) -> ValidationResult:
    """Convenience function to validate a mutation."""
    return PayloadValidator().validate(original, mutated_payload)
