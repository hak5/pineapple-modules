export interface HCXDumptoolState {
    command: string;
    selectedInterface: string;
    scanlist: string;
}

export interface OtherOptions {
    disableClientAttacks: ToggleOption;
    disableAPAttacks: ToggleOption;
}

export interface ToggleOption {
    toggled: boolean,
    value: string
}
