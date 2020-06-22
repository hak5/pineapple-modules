
export interface NmapOptionsState {
    command: string;
    target: string;
    profile: string;
    timing: string;
    tcp: string;
    nontcp: string;
}

export interface ScanOptions {
    advancedOptions: ToggleOption;
    osDetection: ToggleOption;
    versionDetection: ToggleOption;
    disableDNS: ToggleOption;
    ipv6: ToggleOption;
}

export interface PingOptions {
    noPingBeforeScanning: ToggleOption;
    icmpPing: ToggleOption;
    icmpTimeStamp: ToggleOption;
    icmpNetmask: ToggleOption;
}

export interface OtherOptions {
    fragmentPackets: ToggleOption;
    packetTrace: ToggleOption;
    disableRandomized: ToggleOption;
    traceRoutes: ToggleOption;
}

export interface ToggleOption {
    toggled: boolean,
    value: string
}
