import {PortalInfoDTO} from "./portalinfo.interface";

export interface LibraryState {
    showLibrary: boolean;
    isBusy: boolean;
    portals: Array<PortalInfoDTO>;
}
