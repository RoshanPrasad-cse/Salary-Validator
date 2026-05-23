"""
validation/views.py — API endpoint logic (the heart of Person 2's work)

This file handles what happens when someone calls our API endpoints.
It imports Person 1's validator.py and Person 3's ai_validator.py,
runs both, merges scores, and saves to the database.
"""

from django.db.models import Avg, Count, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Submission
from .serializers import SubmissionSerializer, SubmissionInputSerializer

# Import validators — these files are stubs until Person 1 & 3 finish their parts
# If the files don't exist yet, we use a safe fallback so you can still run the server
try:
    from .validator import RuleBasedValidator
except ImportError:
    # Stub fallback — returns a neutral score until Person 1 delivers validator.py
    class RuleBasedValidator:
        def validate(self, data):
            return {"score": 50, "flags": [{"rule": "stub", "severity": "low", "message": "Rule validator not yet integrated"}]}

try:
    from .ai_validator import AIValidator
except ImportError:
    # Stub fallback — returns a neutral score until Person 3 delivers ai_validator.py
    class AIValidator:
        def validate(self, data):
            return {"score": 50, "flags": [{"rule": "stub", "severity": "low", "message": "AI validator not yet integrated"}]}


def calculate_confidence(score):
    """Convert a numeric score to a confidence label."""
    if score >= 75:
        return "high"
    elif score >= 50:
        return "medium"
    else:
        return "low"


def run_validation_pipeline(data: dict) -> dict:
    """
    Core validation pipeline — called for every submission.
    
    1. Run rule-based validator (Person 1)
    2. Run AI validator (Person 3)
    3. Merge: final = (rule * 0.6) + (ai * 0.4)
    4. Return merged result
    """
    # Step 1: Rule-based validation
    rule_validator = RuleBasedValidator()
    rule_result = rule_validator.validate(data)
    rule_score = rule_result.get("score", 50)
    rule_flags = rule_result.get("flags", [])

    # Step 2: AI validation
    ai_validator = AIValidator()
    ai_result = ai_validator.validate(data)
    ai_score = ai_result.get("score", 50)
    ai_flags = ai_result.get("flags", [])

    # Step 3: Merge scores (60/40 split as per contract)
    final_score = int((rule_score * 0.6) + (ai_score * 0.4))

    # Step 4: Merge flags from both validators
    all_flags = rule_flags + ai_flags

    return {
        "overall_score": final_score,
        "rule_score": rule_score,
        "ai_score": ai_score,
        "confidence_level": calculate_confidence(final_score),
        "passed": final_score >= 60,
        "flags": all_flags,
    }


# ── View 1: /api/submissions/ ──────────────────────────────────────────────────

class SubmissionListView(APIView):
    """
    GET  /api/submissions/          → list all submissions
    GET  /api/submissions/?filter=flagged → only flagged ones
    POST /api/submissions/          → validate + save one submission
    """

    def get(self, request):
        """Return all submissions, optionally filtered."""
        queryset = Submission.objects.all()

        # ?filter=flagged — only return submissions that didn't pass
        if request.query_params.get("filter") == "flagged":
            queryset = queryset.filter(passed=False)

        serializer = SubmissionSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Validate a new submission and save it."""
        # Step 1: Validate the incoming JSON shape
        input_serializer = SubmissionInputSerializer(data=request.data)
        if not input_serializer.is_valid():
            return Response(
                {"error": "Invalid input", "details": input_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = input_serializer.validated_data

        # Step 2: Run through both validators
        validation_result = run_validation_pipeline(data)

        # Step 3: Save to database (merge submission data + validation result)
        submission = Submission.objects.create(
            name=data["name"],
            email=data["email"],
            company=data["company"],
            title=data["title"],
            level=data["level"],
            location=data["location"],
            years_of_experience=data["years_of_experience"],
            base_salary=data["base_salary"],
            bonus=data.get("bonus", 0),
            stock_rsu=data.get("stock_rsu", 0),
            total_compensation=data["total_compensation"],
            ip_address=data.get("ip_address"),
            submitted_at=data["submitted_at"],
            # Validation results
            overall_score=validation_result["overall_score"],
            rule_score=validation_result["rule_score"],
            ai_score=validation_result["ai_score"],
            confidence_level=validation_result["confidence_level"],
            passed=validation_result["passed"],
            flags=validation_result["flags"],
        )

        # Step 4: Return the saved submission with validation results
        serializer = SubmissionSerializer(submission)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# ── View 2: /api/submissions/batch/ ───────────────────────────────────────────

class BatchSubmissionView(APIView):
    """
    POST /api/submissions/batch/
    Accepts a list of submissions and validates each one.
    Body: {"submissions": [ {...}, {...} ]}
    """

    def post(self, request):
        submissions_data = request.data.get("submissions", [])

        if not isinstance(submissions_data, list):
            return Response(
                {"error": "Expected a 'submissions' list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        for item in submissions_data:
            input_serializer = SubmissionInputSerializer(data=item)
            if not input_serializer.is_valid():
                results.append({"error": input_serializer.errors, "input": item})
                continue

            data = input_serializer.validated_data
            validation_result = run_validation_pipeline(data)

            submission = Submission.objects.create(
                name=data["name"],
                email=data["email"],
                company=data["company"],
                title=data["title"],
                level=data["level"],
                location=data["location"],
                years_of_experience=data["years_of_experience"],
                base_salary=data["base_salary"],
                bonus=data.get("bonus", 0),
                stock_rsu=data.get("stock_rsu", 0),
                total_compensation=data["total_compensation"],
                ip_address=data.get("ip_address"),
                submitted_at=data["submitted_at"],
                overall_score=validation_result["overall_score"],
                rule_score=validation_result["rule_score"],
                ai_score=validation_result["ai_score"],
                confidence_level=validation_result["confidence_level"],
                passed=validation_result["passed"],
                flags=validation_result["flags"],
            )
            results.append(SubmissionSerializer(submission).data)

        return Response({"results": results}, status=status.HTTP_201_CREATED)


# ── View 3: /api/dashboard/stats/ ─────────────────────────────────────────────

class DashboardStatsView(APIView):
    """
    GET /api/dashboard/stats/
    Returns summary statistics for the frontend dashboard.
    """

    def get(self, request):
        total = Submission.objects.count()
        passed = Submission.objects.filter(passed=True).count()
        flagged = Submission.objects.filter(passed=False).count()

        avg_score_result = Submission.objects.aggregate(avg=Avg("overall_score"))
        average_score = round(avg_score_result["avg"] or 0, 1)

        # Count flags with severity="high" across all submissions
        # flags is a JSONField (list of dicts), so we count submissions that
        # have at least one high-severity flag
        high_severity_count = 0
        for submission in Submission.objects.exclude(flags=[]):
            for flag in submission.flags:
                if isinstance(flag, dict) and flag.get("severity") == "high":
                    high_severity_count += 1

        return Response({
            "total_submissions": total,
            "passed": passed,
            "flagged": flagged,
            "average_score": average_score,
            "high_severity_flags": high_severity_count,
        })
