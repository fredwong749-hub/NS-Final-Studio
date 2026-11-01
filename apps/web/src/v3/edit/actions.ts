// fredw-92/W4b：提交出图 / 视频任务，完成后刷新镜头并选中新版本
import { apiV1, errText, isNotReady, slotToStage, type FrameJobBody, type Slot, type VideoJobBody } from "../api_v1";
import { etaFor, getEdit, gpuLabel, noteJobHistory, pickTake, trackJob } from "./state";
import { paramBody } from "./ImageParams.helpers";

type Notify = (msg: string, kind?: "ok" | "err") => void;
type Refresh = (ids: string[]) => Promise<unknown>;

export const SLOT_NAME: Record<Slot, string> = { first: "首帧", last: "尾帧", video: "视频" };

export async function submitFrame(shot: string, body: FrameJobBody, label: string, notify: Notify, refresh: Refresh) {
  const gpu = body.gpu ?? "auto";
  // fredw-92/PX：带上「出图参数」面板的选择（没选也没改 = 不带，后端用默认预设）；定稿档请求不带
  if (body.preset === undefined && body.params === undefined && body.tier !== "final") body = { ...body, ...paramBody(body.mode) };
  try {
    const { job_id } = await apiV1.frameJob(shot, body);
    trackJob({
      id: job_id,
      shot,
      slot: body.stage,
      label,
      gpu,
      eta_s: etaFor(body.stage, gpu).eta,
      onDone: (j) => {
        void refresh([shot]).then(() => {
          if (j.state === "done" && j.take != null) pickTake(shot, body.stage, j.take);
        });
        notify(j.state === "done" ? `${shot} ${label} 完成${j.take != null ? ` · #${j.take}` : ""}` : `${shot} ${label} 失败：${j.error ?? ""}`, j.state === "done" ? "ok" : "err");
      },
    });
    notify(`已排队：${shot} ${label}（${gpuLabel(gpu)}）`);
    return true;
  } catch (e) {
    notify(`${label}：${errText(e, "W2 /frame-jobs")}`, "err");
    return false;
  }
}

export async function submitVideo(shot: string, body: VideoJobBody, notify: Notify, refresh: Refresh) {
  const gpu = body.gpu ?? "auto";
  try {
    const { job_id, warnings } = await apiV1.videoJob(shot, body);
    trackJob({
      id: job_id,
      shot,
      slot: "video",
      label: "出视频",
      gpu,
      eta_s: etaFor("video", gpu, body.seconds).eta,
      onDone: (j) => {
        void refresh([shot]).then(() => {
          if (j.state === "done" && j.take != null) pickTake(shot, "video", j.take);
        });
        // fredw-92/QCV：出片后运动量质检不合格 → 完成提示里直接说
        const mq = (j as { qc?: { motion?: { verdict?: string; labels?: string[] } } }).qc?.motion;
        const bad = j.state === "done" && mq && mq.verdict !== "pass" ? `（运动质检：${(mq.labels ?? []).join("、") || mq.verdict}）` : "";
        notify(j.state === "done" ? `${shot} 视频完成${bad}` : `${shot} 视频失败：${j.error ?? ""}`, j.state === "done" && mq?.verdict !== "fail" ? "ok" : "err");
      },
    });
    notify(`已排队：${shot} 出视频（${gpuLabel(gpu)}）${warnings?.length ? `。注意：${warnings.join("；")}` : ""}`, warnings?.length ? "err" : "ok");
    return true;
  } catch (e) {
    // 409：首尾帧没定稿，后端写明缺什么，原样显示
    notify(`出视频：${errText(e, "W3 /video-jobs")}`, "err");
    return false;
  }
}

/** F2：任务只记在页面内存里，刷新后会丢。进精修时向后端要本镜进行中的 frame / video 任务，接回任务条继续轮询 */
export async function adoptJobs(shot: string, notify: Notify, refresh: Refresh) {
  const [fj, vt] = await Promise.allSettled([apiV1.frameJobs(shot), apiV1.videoTakes(shot)]);
  const list = [...(fj.status === "fulfilled" ? fj.value : []), ...(vt.status === "fulfilled" ? vt.value.jobs ?? [] : [])];
  noteJobHistory(list as Parameters<typeof noteJobHistory>[0]); // 预计时长按这些实际耗时算
  const known = new Set(getEdit().jobs.map((j) => j.id));
  for (const j of list) {
    const id = j.id ?? j.job_id;
    if (!id || known.has(id) || (j.state !== "queued" && j.state !== "running")) continue;
    const slot: Slot = j.kind === "video" ? "video" : j.params?.stage === "last" ? "last" : "first";
    const label = slot === "video" ? "出视频" : `${j.params?.mode && j.params.mode !== "regen" ? "改" : "重出"}${SLOT_NAME[slot]}`;
    trackJob({
      id,
      shot,
      slot,
      label,
      gpu: j.gpu ?? null,
      eta_s: j.eta_s ?? etaFor(slot, j.gpu ?? "auto").eta,
      started_at: j.started_at,
      onDone: (d) => {
        void refresh([shot]).then(() => {
          if (d.state === "done" && d.take != null) pickTake(shot, slot, d.take);
        });
        notify(d.state === "done" ? `${shot} ${label} 完成` : `${shot} ${label} 失败：${d.error ?? ""}`, d.state === "done" ? "ok" : "err");
      },
    });
  }
}

export async function setLock(shot: string, slot: Slot, n: number, on: boolean, notify: Notify, refresh: Refresh): Promise<boolean> {
  try {
    await apiV1.lockTake(shot, slotToStage(slot), n, on);
    notify(on ? `${shot} ${SLOT_NAME[slot]} #${n} 已定稿` : `${shot} ${SLOT_NAME[slot]} 已取消定稿`);
    await refresh([shot]);
    return true;
  } catch (e) {
    notify(`定稿：${isNotReady(e) ? "后端未就绪（W2 /takes/…/lock）" : (e as Error).message}`, "err");
    return false;
  }
}

/** XYQ（小云雀走查 #1/#2）：定稿当前这一版并直接排下一步——首帧 → 出尾帧（由定稿首帧来，C3）；尾帧 → 出视频。
 *  两步仍走各自的接口与关口：定稿失败就不排下一步；出视频被挡（409）时后端写明缺什么。只是少点一次、不用进精修。 */
export async function lockAndNext(shot: string, slot: "first" | "last", n: number, gpu: FrameJobBody["gpu"], notify: Notify, refresh: Refresh, next = true) {
  if (!(await setLock(shot, slot, n, true, notify, refresh))) return false;
  if (!next) return true; // 下游已经有了（例如整集出片出过）：只定稿，不重复出卡
  if (slot === "first") return submitFrame(shot, { stage: "last", mode: "regen", gpu }, "出尾帧", notify, refresh);
  return submitVideo(shot, { gpu: gpu as VideoJobBody["gpu"] }, notify, refresh);
}
