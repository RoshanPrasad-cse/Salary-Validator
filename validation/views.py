from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Avg, Count, Q

from .models import Submission
from .serializers import SubmissionSerializer

# 1. PERSON 2 CHANGE: Imported get_combined_score alongside AIValidator
from .validator import RuleBasedValidator
from .ai_validator import AIValidator, get_combined_score


class SubmissionListCreateView(APIView):
    """
    Handles POST /api/submissions/ (Submit + Validate)
    Handles GET /api/submissions/  (List with query filtering)
    """

    def get(self, request):
        queryset = Submission.objects.all()

        # Query filter: ?filter=flagged
        filter_param = request.query_params.get("filter", None)
        if filter_param == "flagged":
            queryset = queryset.filter(Q(passed=False) | ~Q(flags=[]))

        serializer = SubmissionSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = SubmissionSerializer(data=request.data)

        # Fix: Standard DRF validation syntax
        if serializer.is_valid():
            submission_data = serializer.validated_data

            # Instantiate both validation engines (Person 1 and Person 3)
            rule_engine = RuleBasedValidator()
            ai_engine = AIValidator()

            # Run independent evaluation pipelines
            rule_result = rule_engine.validate(submission_data)
            ai_result = ai_engine.validate(submission_data)

            rule_score = rule_result.get("score", 0)
            ai_score = ai_result.get("score", 0)

            # 2. PERSON 2 CHANGE: Replaced inline math formula with teammate function
            final_score = get_combined_score(rule_score, ai_score)

            # Aggregate results and flags from both layers
            combined_flags = rule_result.get("flags", []) + ai_result.get(
                "flags", []
            )

            # Calculate confidence dynamically based on final score
            if final_score >= 80:
                confidence = "high"
            elif final_score >= 50:
                confidence = "medium"
            else:
                confidence = "low"

            # Save the fully populated record to the database
            submission = serializer.save(
                ip_address=self.get_client_ip(request),
                rule_score=rule_score,
                ai_score=ai_score,
                overall_score=final_score,
                confidence_level=confidence,
                passed=True if final_score >= 60 else False,
                flags=combined_flags,
            )

            return Response(
                SubmissionSerializer(submission).data,
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


class BatchSubmissionView(APIView):
    """
    Handles POST /api/submissions/batch/
    """

    def post(self, request):
        if not isinstance(request.data, list):
            return Response(
                {"error": "Expected a list of submissions."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        rule_engine = RuleBasedValidator()
        ai_engine = AIValidator()

        for item in request.data:
            serializer = SubmissionSerializer(data=item)
            if serializer.is_valid():
                sub_data = serializer.validated_data
                r_res = rule_engine.validate(sub_data)
                a_res = ai_engine.validate(sub_data)

                r_score = r_res.get("score", 0)
                a_score = a_res.get("score", 0)

                # Person 2 Change applied here for batch requests as well
                f_score = get_combined_score(r_score, a_score)

                sub = serializer.save(
                    rule_score=r_score,
                    ai_score=a_score,
                    overall_score=f_score,
                    confidence_level="high" if f_score >= 80 else "medium",
                    passed=True if f_score >= 60 else False,
                    flags=r_res.get("flags", []) + a_res.get("flags", []),
                )
                results.append(SubmissionSerializer(sub).data)
            else:
                results.append({"error": serializer.errors, "raw_data": item})

        return Response(results, status=status.HTTP_200_OK)


class DashboardStatsView(APIView):
    """
    Handles GET /api/dashboard/stats/
    """

    def get(self, request):
        stats = Submission.objects.aggregate(
            total=Count("id"),
            passed_count=Count("id", filter=Q(passed=True)),
            flagged_count=Count("id", filter=Q(passed=False)),
            avg_score=Avg("overall_score"),
        )

        all_submissions = Submission.objects.all()
        high_severity_count = 0
        for sub in all_submissions:
            for flag in sub.flags:
                if flag.get("severity") == "high":
                    high_severity_count += 1

        return Response(
            {
                "total_submissions": stats["total"] or 0,
                "passed": stats["passed_count"] or 0,
                "flagged": stats["flagged_count"] or 0,
                "average_score": round(stats["avg_score"], 1)
                if stats["avg_score"]
                else 0.0,
                "high_severity_flags": high_severity_count,
            }
        )