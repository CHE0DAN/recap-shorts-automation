import { useState } from "react";
import type { TopicSource } from "../api";
import { Modal, Segmented } from "../ui";
import BestPanel from "./BestPanel";

/** 주제 찾기 시트: 인기글 두 곳 — 디시인사이드 실시간 베스트, 블라인드 토픽 베스트.
 *  '야구 개념글' 탭은 없다(서버의 GET /api/topics?source=gallery 는 그대로 둠).
 *  블라인드(teamblind.com/kr)도 글 출처다 — 탭 이름은 화면에서 '블라인드 인기글'. */
export default function TopicSheet({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<TopicSource>("dcbest");
  return (
    <Modal title="주제 찾기" onClose={onClose} wide>
      <div className="border-b border-line px-6 py-3">
        <Segmented<TopicSource> value={tab} onChange={setTab}
          options={[{ value: "dcbest", label: "디시 인기글" }, { value: "blind", label: "블라인드 인기글" }]} />
      </div>
      <BestPanel source={tab} />
    </Modal>
  );
}
