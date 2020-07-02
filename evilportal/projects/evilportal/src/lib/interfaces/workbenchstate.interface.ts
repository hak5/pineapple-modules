import {PortalInfoDTO} from "./portalinfo.interface";
import {DirectoryDTO} from "./directorydto.interface";

export interface WorkBenchState {
    isBusy: boolean;
    portal: PortalInfoDTO;
    dirContents: Array<DirectoryDTO>;
    inRoot: boolean;
    rootDirectory: string;
}
