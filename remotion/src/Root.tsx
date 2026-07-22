import { Composition } from "remotion";
import { AgentTest } from "./AgentTest";
import { VerticalDemo } from "./VerticalDemo";
import type { AgentTestProps } from "./AgentTest";
import type { TimelineProps } from "./types";

const defaults: TimelineProps = {
  width: 1080,
  height: 1920,
  fps: 30,
  frame_count: 30,
  assets: [],
  shots: [],
  subtitles: [],
};

const agentTestDefaults: AgentTestProps = {
  width: 1080,
  height: 1920,
  fps: 30,
  frame_count: 30,
  voice_path: "",
  title: "Agent Video Test",
  scenes: [],
  subtitles: [],
};

export const Root = () => (
  <>
    <Composition
      id="VerticalDemo"
      component={VerticalDemo}
      defaultProps={defaults}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={30}
      calculateMetadata={({ props }) => ({
        width: props.width,
        height: props.height,
        fps: props.fps,
        durationInFrames: props.frame_count,
      })}
    />
    <Composition
      id="AgentTest"
      component={AgentTest}
      defaultProps={agentTestDefaults}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={30}
      calculateMetadata={({ props }) => ({
        width: props.width,
        height: props.height,
        fps: props.fps,
        durationInFrames: props.frame_count,
      })}
    />
  </>
);
