/* eslint-disable react-refresh/only-export-components */
/**
 * Shared connector icon + color config used by DataSources and DailyDigestGrid.
 */
import type { IconType } from "react-icons";
import {
  SiSalesforce,
  SiHubspot,
  SiSlack,
  SiZoom,
  SiGooglecalendar,
  SiGmail,
  SiGoogledrive,
  SiGithub,
  SiLinear,
  SiJira,
  SiAsana,
} from "react-icons/si";
import {
  HiOutlineCalendar,
  HiOutlineMail,
  HiGlobeAlt,
  HiDeviceMobile,
  HiMicrophone,
  HiLightningBolt,
  HiDocumentText,
  HiCube,
  HiLink,
} from "react-icons/hi";

const ApolloIcon: IconType = ({ className, ...props }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    className={className}
    {...props}
  >
    <line x1="12" y1="2" x2="12" y2="22" />
    <line x1="2" y1="12" x2="22" y2="12" />
    <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
    <line x1="19.07" y1="4.93" x2="4.93" y2="19.07" />
  </svg>
);

/** Trello brand mark (canonical board logo; fill matches official blue on light UI). */
const TrelloIcon: IconType = ({ className, ...props }) => (
  <svg
    viewBox="0 0 24 24"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden
    className={className}
    {...props}
  >
    <path
      fill="currentColor"
      d="M21.147 0H2.853A2.853 2.853 0 0 0 0 2.853v18.294A2.853 2.853 0 0 0 2.853 24h18.294A2.853 2.853 0 0 0 24 21.147V2.853A2.853 2.853 0 0 0 21.147 0ZM10.707 19.207c0 .643-.523 1.167-1.167 1.167H5.565c-.643 0-1.167-.523-1.167-1.167V6.565c0-.643.523-1.167 1.167-1.167h4.075c.643 0 1.167.523 1.167 1.167v12.642Zm10.028-10.68c0 .643-.523 1.167-1.167 1.167h-4.075c-.643 0-1.167-.523-1.167-1.167V6.565c0-.643.523-1.167 1.167-1.167h4.075c.643 0 1.167.523 1.167 1.167v2.063Z"
    />
  </svg>
);

/** Attio brand mark (paths from attio.com Storyblok asset; stroke uses theme color). */
const AttioIcon: IconType = ({ className, ...props }) => (
  <svg viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg" className={className} {...props}>
    <path
      d="M16.7802 11.5317L15.4723 9.43851C15.4723 9.43851 15.4674 9.42975 15.4645 9.42586L15.3613 9.2614C15.1667 8.94902 14.83 8.76218 14.4622 8.76121L12.3553 8.75439L12.2084 8.98989L9.69085 13.0187L9.55169 13.2415L10.6066 14.927C10.8012 15.2404 11.1379 15.4272 11.5087 15.4272H14.4612C14.8251 15.4272 15.1696 15.2355 15.3623 14.928L15.4664 14.7616C15.4664 14.7616 15.4703 14.7567 15.4713 14.7548L16.7812 12.6586C16.9962 12.3161 16.9962 11.8733 16.7812 11.5317H16.7802ZM16.3812 12.4085L15.0714 14.5047C15.0655 14.5144 15.0587 14.5222 15.0529 14.53C15.0071 14.5816 14.9478 14.5884 14.9215 14.5884C14.8913 14.5884 14.8174 14.5796 14.7697 14.5037L13.4598 12.4076C13.4452 12.3842 13.4326 12.3599 13.4209 12.3336C13.4092 12.3083 13.4005 12.283 13.3927 12.2567C13.3635 12.1516 13.3635 12.0387 13.3927 11.9336C13.4073 11.8821 13.4297 11.8305 13.4589 11.7838L14.7668 9.68958C14.7668 9.68958 14.7687 9.68666 14.7697 9.68472C14.8008 9.63801 14.8397 9.6166 14.8738 9.60979C14.8874 9.60589 14.8991 9.60492 14.9088 9.60297C14.9137 9.60297 14.9186 9.60297 14.9234 9.60297C14.9536 9.60297 15.0285 9.61271 15.0752 9.68861L16.3831 11.7818C16.5028 11.9726 16.5028 12.2178 16.3831 12.4085H16.3812Z"
      stroke="currentColor"
      strokeWidth={1.2}
    />
    <path
      d="M12.9099 6.46677C13.124 6.12325 13.124 5.68145 12.9099 5.33988L11.602 3.24665L11.493 3.07051C11.2974 2.75813 10.9607 2.57129 10.5909 2.57129H7.63838C7.26956 2.57129 6.93285 2.75813 6.73628 3.07148L1.4492 11.5329C1.34313 11.7023 1.28571 11.8979 1.28571 12.0964C1.28571 12.2949 1.34216 12.4905 1.44823 12.6589L2.8661 14.9292C3.0617 15.2426 3.3984 15.4284 3.76722 15.4284H6.71974C7.0905 15.4284 7.42721 15.2416 7.62184 14.9282L7.72986 14.757C7.72986 14.757 7.72986 14.757 7.72986 14.755C7.72986 14.755 7.7318 14.7521 7.7318 14.7511L8.78572 13.0656L11.9095 8.06662L12.9079 6.46775L12.9099 6.46677ZM12.6014 5.90332C12.6014 6.01134 12.5712 6.12034 12.5099 6.21668L7.33087 14.5059C7.28416 14.5808 7.20923 14.5896 7.17906 14.5896C7.14889 14.5896 7.07493 14.5808 7.02725 14.5059L5.71837 12.4088C5.59965 12.219 5.59965 11.9748 5.71837 11.783L10.8974 3.49577C10.9441 3.41987 11.0191 3.41111 11.0492 3.41111C11.0794 3.41111 11.1543 3.41987 11.202 3.49675L12.5099 5.58997C12.5712 5.68631 12.6014 5.79531 12.6014 5.90332V5.90332Z"
      stroke="currentColor"
      strokeWidth={1.2}
    />
  </svg>
);

export const CONNECTOR_ICON_MAP: Record<string, IconType> = {
  hubspot: SiHubspot,
  salesforce: SiSalesforce,
  slack: SiSlack,
  zoom: SiZoom,
  "google-calendar": SiGooglecalendar,
  google_calendar: SiGooglecalendar,
  gmail: SiGmail,
  "microsoft-calendar": HiOutlineCalendar,
  microsoft_calendar: HiOutlineCalendar,
  "microsoft-mail": HiOutlineMail,
  microsoft_mail: HiOutlineMail,
  fireflies: HiMicrophone,
  google_drive: SiGoogledrive,
  apollo: ApolloIcon,
  github: SiGithub,
  linear: SiLinear,
  jira: SiJira,
  asana: SiAsana,
  trello: TrelloIcon,
  attio: AttioIcon,
  globe: HiGlobeAlt,
  terminal: HiLightningBolt,
  sms: HiDeviceMobile,
  artifacts: HiDocumentText,
  apps: HiCube,
  plug: HiLink,
};

export interface ConnectorDisplay {
  icon: string;
  color: string;
  label: string;
}

export const CONNECTOR_DISPLAY: Record<string, ConnectorDisplay> = {
  hubspot: { icon: "hubspot", color: "from-orange-500 to-orange-600", label: "HubSpot" },
  salesforce: { icon: "salesforce", color: "from-blue-500 to-blue-600", label: "Salesforce" },
  slack: { icon: "slack", color: "from-purple-500 to-purple-600", label: "Slack" },
  zoom: { icon: "zoom", color: "from-blue-400 to-blue-500", label: "Zoom" },
  google_calendar: { icon: "google_calendar", color: "from-green-500 to-green-600", label: "Google Calendar" },
  gmail: { icon: "gmail", color: "from-red-500 to-red-600", label: "Gmail" },
  microsoft_calendar: { icon: "microsoft_calendar", color: "from-sky-500 to-sky-600", label: "Microsoft Calendar" },
  microsoft_mail: { icon: "microsoft_mail", color: "from-sky-500 to-sky-600", label: "Microsoft Mail" },
  fireflies: { icon: "fireflies", color: "from-violet-500 to-violet-600", label: "Fireflies" },
  granola: { icon: "/connector-icons/granola.png", color: "from-lime-500 to-green-600", label: "Granola" },
  google_drive: { icon: "google_drive", color: "from-yellow-500 to-amber-500", label: "Google Drive" },
  apollo: { icon: "apollo", color: "from-yellow-400 to-yellow-500", label: "Apollo" },
  github: { icon: "github", color: "from-gray-600 to-gray-700", label: "GitHub" },
  linear: { icon: "linear", color: "from-indigo-500 to-violet-600", label: "Linear" },
  jira: { icon: "jira", color: "from-blue-500 to-blue-600", label: "Jira" },
  asana: { icon: "asana", color: "from-fuchsia-500 to-pink-600", label: "Asana" },
  trello: { icon: "trello", color: "from-blue-600 to-sky-500", label: "Trello" },
  attio: { icon: "attio", color: "from-fuchsia-500 to-purple-600", label: "Attio" },
  web_search: { icon: "globe", color: "from-emerald-500 to-teal-600", label: "Web Search" },
  code_sandbox: { icon: "terminal", color: "from-amber-500 to-orange-600", label: "Code Sandbox" },
  twilio: { icon: "sms", color: "from-red-500 to-pink-600", label: "Twilio" },
  artifacts: { icon: "artifacts", color: "from-slate-500 to-slate-600", label: "Artifacts" },
  apps: { icon: "apps", color: "from-violet-500 to-purple-600", label: "Apps" },
  mcp: { icon: "plug", color: "from-cyan-500 to-blue-600", label: "MCP" },
  ispot_tv: { icon: "globe", color: "from-emerald-500 to-teal-600", label: "iSpot.tv" },
  meetings: { icon: "fireflies", color: "from-violet-500 to-violet-600", label: "Meeting Notes" },
};

export const DEFAULT_CONNECTOR_ICON = "globe";
export const DEFAULT_CONNECTOR_COLOR = "from-gray-500 to-gray-600";

export function isImageIcon(iconId: string): boolean {
  return iconId.startsWith("/") || iconId.startsWith("http");
}

export function getConnectorColorClass(color: string): string {
  const colorMap: Record<string, string> = {
    "from-orange-500 to-orange-600": "bg-orange-500",
    "from-blue-500 to-blue-600": "bg-blue-500",
    "from-blue-400 to-blue-500": "bg-blue-400",
    "from-purple-500 to-purple-600": "bg-purple-500",
    "from-green-500 to-green-600": "bg-green-500",
    "from-sky-500 to-sky-600": "bg-sky-500",
    "from-red-500 to-red-600": "bg-red-500",
    "from-violet-500 to-violet-600": "bg-violet-500",
    "from-yellow-400 to-yellow-500": "bg-yellow-400",
    "from-yellow-500 to-amber-500": "bg-yellow-500",
    "from-indigo-500 to-violet-600": "bg-indigo-500",
    "from-gray-600 to-gray-700": "bg-gray-600",
    "from-gray-500 to-gray-600": "bg-gray-500",
    "from-emerald-500 to-teal-600": "bg-emerald-500",
    "from-lime-500 to-green-600": "bg-lime-500",
    "from-fuchsia-500 to-pink-600": "bg-fuchsia-500",
    "from-fuchsia-500 to-purple-600": "bg-fuchsia-500",
    "from-amber-500 to-orange-600": "bg-amber-500",
    "from-red-500 to-pink-600": "bg-red-500",
    "from-slate-500 to-slate-600": "bg-slate-500",
    "from-cyan-500 to-blue-600": "bg-cyan-500",
    "from-blue-600 to-sky-500": "bg-blue-600",
  };
  return colorMap[color] ?? "bg-surface-600";
}

export function renderConnectorIcon(iconId: string, sizeClass: string): JSX.Element {
  if (isImageIcon(iconId)) {
    return <img src={iconId} alt="" className={`${sizeClass} rounded object-cover`} />;
  }
  const IconComponent = CONNECTOR_ICON_MAP[iconId] ?? HiGlobeAlt;
  return <IconComponent className={sizeClass} />;
}
