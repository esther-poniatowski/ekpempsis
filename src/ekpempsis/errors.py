"""Errors exposed by the Ekpempsis command surface."""


class EkpempsisError(Exception):
    """Report a configuration, validation, Git, or publication failure."""


class PublicationUnconfirmedError(EkpempsisError):
    """Report that a push succeeded but provider availability was not confirmed."""

    def __init__(self, branch: str, detail: str) -> None:
        self.pushed = True
        self.branch = branch
        self.detail = detail
        super().__init__(
            f"pushed branch {branch}, but provider availability is unconfirmed: {detail}"
        )
