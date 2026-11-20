# Building simulated payment processor as processing will produce different outcomes: approved, declined or timeout
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

#@dataclass automatically provides the constructor for this result object.
@dataclass(frozen=True)         #frozen=True prevents ordinary reassignment of its fields after creation.
class ProcessorResult:
    status: Literal["succeeded", "failed", "unknown"]             #status describes the processing outcome. Literal documents the allowed values for type checking; it doesn’t validate them at runtime.
    processor_reference: str | None = None                        #processor_reference holds the simulator’s transaction reference, when available.
    error_code: str | None = None                                 #error_code explains a decline or timeout.


#Returns a successful simulated result with a reference such as sim-<payment UUID>.
def simulate_payment(payment_id: UUID) -> ProcessorResult:
    return ProcessorResult(
        status="succeeded",
        processor_reference=f"sim-{payment_id}",
    )