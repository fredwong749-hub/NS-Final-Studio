// 次要视图：用 @xyflow/react 把本集 6 镜画成链，便于看首→尾帧衔接。
// 规范 C1：主视图是固定网格；此视图按需懒加载，不在主路径上。
import { useMemo } from "react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useStudio } from "../store";
import { seamState } from "./Seam";
import { ShotCard, type ShotCardProps } from "./ShotCard";

type Data = Omit<ShotCardProps, "onClick">;
type ShotNode = Node<Data, "shot">;

function ShotNodeView({ data }: NodeProps<ShotNode>) {
  return (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <ShotCard {...data} onClick={() => undefined} />
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </>
  );
}
const nodeTypes = { shot: ShotNodeView };

export default function NodeView() {
  const { episode, details, latest, sel, multi, select } = useStudio();
  const shots = useMemo(() => episode?.shots ?? [], [episode]);
  const nodes = useMemo<ShotNode[]>(
    () =>
      shots.map((s, i) => ({
        id: s.id,
        type: "shot",
        position: { x: i * 260, y: 0 },
        draggable: false,
        selectable: false,
        data: { s, detail: details[s.id], job: latest.get(s.id), selected: s.id === sel, inMulti: multi.has(s.id), density: "compact" },
      })),
    [shots, details, latest, sel, multi],
  );
  const edges = useMemo<Edge[]>(
    () =>
      shots.slice(0, -1).map((s, i) => {
        const { state } = seamState(s, shots[i + 1]);
        return {
          id: `${s.id}>${shots[i + 1].id}`,
          source: s.id,
          target: shots[i + 1].id,
          animated: state === "linked",
          className: `edge-${state}`,
          label: { linked: "尾帧=下一镜首帧", stale: "已过期", custom: "自定义尾帧", none: undefined }[state],
          markerEnd: { type: MarkerType.ArrowClosed },
        };
      }),
    [shots],
  );
  return (
    <div className="flow-view">
      <ReactFlow
        key={episode?.number}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(e, n) => select(n.id, { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey })}
        fitView
        minZoom={0.2}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
      >
        <Background gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
