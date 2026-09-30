import happy from "./happy-path-payment.json";
import decline from "./decline.json";
import wrong from "./wrong-verifier.json";
import agent from "./request-agent.json";
import spoken from "./spoken-card.json";

export type ScenarioStep =
  | { user: string; expectState?: string; expectReply?: string; waitFor?: never }
  | { waitFor: "payment_result" | "secure_capture"; expectState?: string; user?: never };

export type Scenario = {
  id: string;
  name: string;
  accountId?: string;
  hint?: string;
  steps: ScenarioStep[];
};

export const SCENARIOS: Scenario[] = [happy, decline, wrong, agent, spoken] as Scenario[];
