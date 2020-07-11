<?php namespace evilportal;

class API
{
    private $request;
    private $error;

    public function __construct()
    {
        $this->request = (object)$_POST;
    }

    public function route()
    {
        $portalPath = "/www/MyPortal.php";
        $portalClass = "evilportal\\MyPortal";

        if (!file_exists($portalPath)) {
            $this->error = "MyPortal.php does not exist in {$portalPath}";
            return;
        }

        require_once("Portal.php");
        require_once($portalPath);

        if (!class_exists($portalClass)) {
            $this->error = "The class {$portalClass} does not exist in {$portalPath}";
            return;
        }

        $portal = new $portalClass($this->request);
        $portal->handleAuthorization();
        $this->response = $portal->getResponse();
    }

    public function finalize()
    {
        if ($this->error) {
            return json_encode(array("error" => $this->error));
        } elseif ($this->response) {
            return json_encode($this->response);
        }
    }

    public function go()
    {
        $this->route();
    }
}
