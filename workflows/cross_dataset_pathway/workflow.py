"""CrossDatasetPathwayWorkflow definition."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows.cross_dataset_pathway.schemas import (
        CrossDatasetPathwayInput,
        CrossDatasetPathwayOutput,
    )


@workflow.defn
class CrossDatasetPathwayWorkflow:
    """Workflow for cross-dataset pathway analysis.

    Steps:
    1. Fetch privacy-preserving pathway summaries for each dataset
    2. Aggregate pathway scores using meta-analysis methods
    3. Optionally call LLM for biological interpretation
    4. Persist results to database
    """

    @workflow.run
    async def run(self, input: CrossDatasetPathwayInput) -> CrossDatasetPathwayOutput:
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=60),
            backoff_coefficient=2.0,
            maximum_attempts=3,
        )

        analysis_id_str = str(input.analysis_id)
        org_id_str = str(input.organization_id)
        dataset_id_strs = [str(d) for d in input.dataset_ids]

        workflow.logger.info(
            f"Starting CrossDatasetPathwayWorkflow analysis={analysis_id_str}, "
            f"datasets={len(dataset_id_strs)}, db={input.pathway_database}"
        )

        try:
            # Step 1: Fetch dataset pathway summaries (privacy-preserving)
            fetch_result = await workflow.execute_activity(
                "fetch_datasets",
                {
                    "analysis_id": analysis_id_str,
                    "dataset_ids": dataset_id_strs,
                    "pathway_database": input.pathway_database,
                },
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            # Step 2: Aggregate pathway patterns across datasets
            aggregate_result = await workflow.execute_activity(
                "aggregate_pathways",
                {
                    "dataset_summaries": fetch_result["dataset_summaries"],
                    "aggregation_method": input.aggregation_method,
                },
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=retry_policy,
            )

            patterns = aggregate_result["patterns"]

            # Step 3: Optional LLM interpretation
            interpretation = None
            hypotheses: list = []
            llm_model_used = None
            llm_cost_usd = None

            if input.llm_model:
                llm_result = await workflow.execute_activity(
                    "call_llm",
                    {
                        "analysis_id": analysis_id_str,
                        "organization_id": org_id_str,
                        "patterns": patterns,
                        "llm_model": input.llm_model,
                    },
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=2),
                        maximum_interval=timedelta(seconds=30),
                        backoff_coefficient=2.0,
                        maximum_attempts=3,
                    ),
                )
                interpretation = llm_result.get("interpretation")
                hypotheses = llm_result.get("hypotheses", [])
                llm_model_used = llm_result.get("model_used")
                llm_cost_usd = llm_result.get("cost_usd")

            # Step 4: Persist results
            await workflow.execute_activity(
                "update_analysis_status",
                {
                    "analysis_id": analysis_id_str,
                    "status": "completed",
                    "patterns": patterns,
                    "interpretation": interpretation,
                    "hypotheses": hypotheses,
                    "llm_model_used": llm_model_used,
                    "llm_cost_usd": llm_cost_usd,
                },
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=retry_policy,
            )

            workflow.logger.info(
                f"CrossDatasetPathwayWorkflow completed: {len(patterns)} patterns found"
            )

            from workflows.cross_dataset_pathway.schemas import PathwayPattern

            return CrossDatasetPathwayOutput(
                analysis_id=input.analysis_id,
                status="completed",
                patterns=[PathwayPattern(**p) for p in patterns],
                interpretation=interpretation,
                hypotheses=hypotheses,
                llm_model_used=llm_model_used,
                llm_cost_usd=llm_cost_usd,
            )

        except Exception as e:
            workflow.logger.error(f"CrossDatasetPathwayWorkflow failed: {e}")

            # Compensation: mark analysis as failed
            try:
                await workflow.execute_activity(
                    "update_analysis_status",
                    {
                        "analysis_id": analysis_id_str,
                        "status": "failed",
                        "error_message": str(e),
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except Exception as comp_err:
                workflow.logger.error(f"Compensation failed: {comp_err}")

            return CrossDatasetPathwayOutput(
                analysis_id=input.analysis_id,
                status="failed",
                patterns=[],
                error_message=str(e),
            )
