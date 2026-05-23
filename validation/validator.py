import datetime


class RuleBasedValidator:
    """
    Rule-based validation engine for Levels.fyi crowd-sourced data.
    Implements the System Interface Contract: validate(data: dict) -> dict
    """

    def __init__(self):
        # Rough realistic boundaries for tech roles (Base, Stock, Bonus)
        # Scaled dynamically by experience level or tier in production
        self.MAX_BASE_SALARY = 1000000  # $1M
        self.MIN_BASE_SALARY = 30000    # $30K (global lower bound for full-time tech)
        self.MAX_TOTAL_COMP = 5000000   # $5M

    def validate(self, data: dict) -> dict:
        """
        Validates submission data using deterministic rules.
        
        Args:
            data (dict): The raw submission matching the system data format.
            
        Returns:
            dict: {"score": int, "flags": list}
        """
        flags = []
        deductions = 0

        try:
            # 1. Safely extract core values with defaults to prevent crashes
            base = float(data.get("base_salary") or 0)
            bonus = float(data.get("bonus") or 0)
            stock = float(data.get("stock_rsu") or 0)
            tc = float(data.get("total_compensation") or 0)
            yoe = float(data.get("years_of_experience") or 0)
            level = str(data.get("level") or "").upper().strip()
            title = str(data.get("title") or "").lower()

            # 2. Rule: Total Compensation Mathematical Check
            # TC should always equal base + bonus + stock. Allow small rounding leeway ($100).
            calculated_tc = base + bonus + stock
            if abs(tc - calculated_tc) > 100:
                severity = "high" if abs(tc - calculated_tc) > 10000 else "medium"
                flags.append({
                    "rule": "tc_math_mismatch",
                    "severity": severity,
                    "message": f"Reported TC (${tc:,.0f}) does not match calculated sum of Base, Bonus, and RSU (${calculated_tc:,.0f})."
                })
                deductions += 30 if severity == "high" else 15

            # 3. Rule: Outlier Salary Check (Too Low / Too High)
            if base < self.MIN_BASE_SALARY:
                flags.append({
                    "rule": "salary_range_check",
                    "severity": "high",
                    "message": f"Base salary of ${base:,.0f} is suspiciously low for a professional tech role."
                })
                deductions += 40
            elif base > self.MAX_BASE_SALARY or tc > self.MAX_TOTAL_COMP:
                flags.append({
                    "rule": "salary_range_check",
                    "severity": "high",
                    "message": f"Compensation metrics are extreme outlier numbers (Base: ${base:,.0f}, TC: ${tc:,.0f})."
                })
                deductions += 50

            # 4. Rule: Level vs Experience Consistency
            # Catching senior titles/levels with 0 YOE, or entry levels claiming high YOE
            is_senior_title = any(kw in title for kw in ["senior", "sr", "lead", "principal", "staff", "manager"])
            is_senior_level = any(lvl in level for lvl in ["L5", "L6", "L7", "L8", "E5", "E6", "IC5", "IC6"])
            
            if (is_senior_title or is_senior_level) and yoe < 2:
                flags.append({
                    "rule": "experience_level_mismatch",
                    "severity": "high",
                    "message": f"Senior level/title '{level} {data.get('title')}' reported with unusually low experience ({yoe} YOE)."
                })
                deductions += 25
            elif "entry" in title or "junior" in title or "jr" in title or level in ["L3", "E3", "L1", "L2"]:
                if yoe > 8:
                    flags.append({
                        "rule": "experience_level_mismatch",
                        "severity": "medium",
                        "message": f"Junior/Entry title reported with very high experience ({yoe} YOE)."
                    })
                    deductions += 15

            # 5. Rule: Missing Core Fields
            required_fields = ["company", "title", "level", "location"]
            for field in required_fields:
                if not data.get(field) or str(data.get(field)).strip() == "":
                    flags.append({
                        "rule": "missing_critical_data",
                        "severity": "high",
                        "message": f"Critical field '{field}' is missing or blank."
                    })
                    deductions += 20

            # 6. Rule: Future or Malformed Timestamps
            submitted_at_str = data.get("submitted_at")
            if submitted_at_str:
                try:
                    # Clean up string if it contains 'Z' or offset format for parsing
                    clean_ts = submitted_at_str.replace("Z", "").split("+")[0]
                    submitted_at = datetime.datetime.fromisoformat(clean_ts)
                    if submitted_at > datetime.datetime.now():
                        flags.append({
                            "rule": "suspicious_timestamp",
                            "severity": "medium",
                            "message": "Submission timestamp points to a future date."
                        })
                        deductions += 15
                except ValueError:
                    flags.append({
                        "rule": "invalid_timestamp_format",
                        "severity": "low",
                        "message": "Timestamp format is invalid or can't be parsed."
                    })
                    deductions += 5

            # Calculate score safely between 0 and 100
            score = max(0, 100 - deductions)
            return {
                "score": int(score),
                "flags": flags
            }

        except Exception as e:
            # System Interface Contract Safeguard: System must never crash
            return {
                "score": 0,
                "flags": [{
                    "rule": "system_validation_exception",
                    "severity": "high",
                    "message": f"Fatal execution exception in rule engine: {str(e)}"
                }]
            }