package com.demo.web;

import org.springframework.web.bind.annotation.*;

/**
 * 보호자 API.
 */
@RestController
@RequestMapping("/api")
public class OwnerController {

    private final OwnerService ownerService;

    public OwnerController(OwnerService ownerService) {
        this.ownerService = ownerService;
    }

    @PostMapping("/owners")
    public ResponseEntity<OwnerDto> addOwner(@RequestBody OwnerDto dto) {
        Owner owner = ownerService.save(dto.toEntity());
        return ResponseEntity.status(201).body(OwnerDto.of(owner));
    }

    @GetMapping("/owners")
    public List<OwnerDto> listOwners(@RequestParam(required = false) String lastName) {
        if (lastName != null) {
            return ownerService.findByLastName(lastName);
        }
        return ownerService.findAll();
    }

    @DeleteMapping("/owners/{ownerId}")
    public ResponseEntity<Void> deleteOwner(@PathVariable Integer ownerId) {
        ownerService.delete(ownerId);
        return ResponseEntity.noContent().build();
    }
}
