class DomainError(Exception):
    """Terminal application error. Dramatiq is configured NOT to retry subclasses.

    Transient infrastructure errors (broker disconnect, storage timeout,
    DB deadlock) must raise something that is NOT a DomainError so the
    worker's retry middleware takes effect.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
