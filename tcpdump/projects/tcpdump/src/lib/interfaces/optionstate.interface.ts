export interface TCPDumpState {
    command: string;
    selectedInterface: string;
    filter: string;
    timestamp: string;
    resolve: string;
    verbose: string;
}

export interface OtherOptions {
    dontPrintHostName: ToggleOption;
    showHexAndASCII: ToggleOption;
    printAbsoluteNumbers: ToggleOption;
    getEthernetHeaders: ToggleOption;
    lessProtocolInfo: ToggleOption;
    monitorMode: ToggleOption;
}

export interface ToggleOption {
    toggled: boolean,
    value: string
}
