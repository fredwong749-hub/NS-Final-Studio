"""参考素材的来源与授权。真人来源的素材没有授权记录就不能进入渲染。"""
from typing import Literal

from pydantic import BaseModel, model_validator

Provenance = Literal["generated", "licensed", "real_person"]


class ReferenceAsset(BaseModel):
    id: str  # 如 REF-LW-01
    path: str
    sha256: str
    provenance: Provenance
    # real_person 必填：本人书面同意（含成人内容用途）的记录编号
    consent_record_id: str | None = None
    # licensed 必填：授权来源或合同编号
    license_ref: str | None = None

    @model_validator(mode="after")
    def _check_rights(self):
        if self.provenance == "real_person" and not self.consent_record_id:
            raise ValueError(f"{self.id}: 真人参考图必须有本人同意记录 consent_record_id")
        if self.provenance == "licensed" and not self.license_ref:
            raise ValueError(f"{self.id}: 授权素材必须写 license_ref")
        return self
