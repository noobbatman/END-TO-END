from app.extraction.bank_statement import BankStatementExtractor
from app.extraction.base import Extractor
from app.extraction.contract import ContractExtractor
from app.extraction.invoice import InvoiceExtractor
from app.extraction.receipt import ReceiptExtractor
from app.extraction.unknown import UnknownExtractor

_REGISTRY: dict[str, type[Extractor]] = {
    "invoice": InvoiceExtractor,
    "bank_statement": BankStatementExtractor,
    "receipt": ReceiptExtractor,
    "contract": ContractExtractor,
}


def get_extractor(document_type: str) -> Extractor:
    cls = _REGISTRY.get(document_type, UnknownExtractor)
    return cls()
