"""Abstract base class for Zerna scientific method definitions."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from zerna_contracts.enums import ComputePreference
from opentelemetry import trace
from pydantic import BaseModel

if TYPE_CHECKING:
    from zerna_gpu_abstraction.compute_context import ComputeContext

_tracer = trace.get_tracer("zerna.methods")


class MethodDefinition(ABC):
    """Abstract base class for all Zerna scientific methods.

    Subclasses must define name, version, compute_preference, and implement
    input_schema, output_schema, and execute.
    """

    name: str
    version: str
    compute_preference: ComputePreference = ComputePreference.GPU_PREFERRED

    @abstractmethod
    def input_schema(self) -> type[BaseModel]:
        """Return the Pydantic model class used to validate method inputs."""
        ...

    @abstractmethod
    def output_schema(self) -> type[BaseModel]:
        """Return the Pydantic model class used to validate method outputs."""
        ...

    @abstractmethod
    def execute(self, input: BaseModel, compute: "ComputeContext") -> BaseModel:
        """Execute the method with validated input and a compute context.

        Args:
            input: Validated input model instance.
            compute: ComputeContext providing hardware resource management.

        Returns:
            Validated output model instance.
        """
        ...

    def execute_traced(
        self,
        input: BaseModel,
        compute: "ComputeContext",
        run_id: str | None = None,
        org_id: str | None = None,
    ) -> BaseModel:
        """Execute the method wrapped in an OpenTelemetry span.

        Span attributes include method_name, method_version, run_id, and org_id
        so that traces can be correlated with Control Plane runs.

        Args:
            input: Validated input model instance.
            compute: ComputeContext providing hardware resource management.
            run_id: Optional run identifier for span correlation.
            org_id: Optional organization identifier.

        Returns:
            Validated output model instance.
        """
        span_name = f"method.{getattr(self, 'name', type(self).__name__)}"
        with _tracer.start_as_current_span(span_name) as span:
            span.set_attribute("method.name", getattr(self, "name", type(self).__name__))
            span.set_attribute("method.version", getattr(self, "version", "unknown"))
            if run_id:
                span.set_attribute("run_id", run_id)
            if org_id:
                span.set_attribute("org_id", org_id)
            try:
                result = self.execute(input, compute)
                span.set_status(trace.StatusCode.OK)
                return result
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise

    def validate_input(self, data: dict[str, Any]) -> BaseModel:
        """Validate input data against input_schema.

        Args:
            data: Raw input dictionary to validate.

        Returns:
            Validated Pydantic model instance.

        Raises:
            pydantic.ValidationError: If data does not match the input schema.
        """
        return self.input_schema()(**data)

    def validate_output(self, data: dict[str, Any]) -> BaseModel:
        """Validate output data against output_schema.

        Args:
            data: Raw output dictionary to validate.

        Returns:
            Validated Pydantic model instance.

        Raises:
            pydantic.ValidationError: If data does not match the output schema.
        """
        return self.output_schema()(**data)
